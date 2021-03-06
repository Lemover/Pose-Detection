import tensorflow as tf
import numpy as np
import model.networks as networks
import load_data.load_data as load_data
import visualization.visual as visual
import os

project_path = 'D:\\UserData\\DeepLearning\\Pose-Detection\\'

class Stacked_Hourglass():
    def __init__(self, block_number, layers, out_dim, point_num, lr, training=True, dropout_rate=0.2):
        self.block_number = block_number
        self.layers = layers
        self.out_dim = out_dim
        self.point_num = point_num
        self.lr = lr
        self.training = training
        self.dropout_rate = dropout_rate
        self.input = tf.placeholder(tf.float32, shape=[None, 256, 256, 3], name='input_image')
        self.label = tf.placeholder(tf.float32, shape=[None, 64, 64, 14], name='input_label')

        with tf.variable_scope('hourglass0_down_sampling'):
            self.mid = networks.set_conv(self.input, 6, 64, 2, 'compression')  # down sampling
            self.mid = networks.set_res(self.mid, 128, 'compression_res0')
            self.mid = tf.nn.max_pool(self.mid, ksize=[1, 2, 2, 1], strides=[1, 2, 2, 1], padding='SAME')  # down sampling
            self.mid = networks.set_res(self.mid, 128, 'compression_res1')
            self.mid = networks.set_res(self.mid, out_dim, 'compression_res2')

        hgout0 = networks.set_hourglass(input=self.mid, layers=layers, out_dim=out_dim, scope='hourglass0')
        with tf.variable_scope('hourglass0_back'):
            hgout_conv1 = networks.set_conv(hgout0, 1, out_dim, 1, 'hgout0_conv0')
            hgout_conv2 = networks.set_conv(hgout_conv1, 1, out_dim, 1, 'hgout0_conv1')

            pred = networks.set_conv(hgout_conv1, 1, point_num, 1, 'pred0')
            heat_map = [pred]
            heat_map_reshape = networks.set_conv(pred, 1, out_dim, 1, 'reshape0')

            hgin1 = tf.add_n([self.mid, hgout_conv2, heat_map_reshape])
        hgin = [hgin1]

        for i in range(1, self.block_number):
            hgout0 = networks.set_hourglass(input=hgin[i-1], layers=layers, out_dim=out_dim, scope='hourglass'+str(i))
            with tf.variable_scope('hourglass'+str(i)+'_back'):
                hgout0 = tf.layers.dropout(hgout0, rate=self.dropout_rate, training=self.training, name='dropout'+str(i))
                hgout_conv1 = networks.set_conv(hgout0, 1, out_dim, 1, 'hgout'+str(i)+'_conv0')
                hgout_conv1 = tf.contrib.layers.batch_norm(hgout_conv1, 0.9, epsilon=1e-5, activation_fn=tf.nn.relu,
                                                           scope='hgout'+str(i)+'_batch')
                hgout_conv2 = networks.set_conv(hgout_conv1, 1, out_dim, 1, 'hgout'+str(i)+'_conv1')

                pred = networks.set_conv(hgout_conv1, 1, point_num, 1, 'pred'+str(i), activate="sigmoid")
                heat_map.append(pred)
                heat_map_reshape = networks.set_conv(pred, 1, out_dim, 1, 'reshape'+str(i))

                hgin1 = tf.add_n([hgin[i-1], hgout_conv2, heat_map_reshape])
            hgin.append(hgin1)

        self.output_mean = tf.reduce_mean(heat_map, 0)
        self.step_output = heat_map
        self.output = pred
        self.loss_sum = tf.nn.l2_loss(tf.subtract(heat_map, self.label))
        self.loss = tf.nn.l2_loss(tf.subtract(self.output, self.label))

        self.optimizer = tf.train.RMSPropOptimizer(lr).minimize(self.loss)

        var = []
        step_loss = []
        for i in range(self.block_number):
            step_loss.append(tf.nn.l2_loss(tf.subtract(heat_map[i], self.label)))
            var.append([v for v in tf.trainable_variables() if v.name.startswith("hourglass" + str(i))])
        self.step_loss = step_loss
        self.step_var = var

        self.saver = tf.train.Saver(max_to_keep=2)

    def train(self, image_path, label_path, batch_size, maxepoch, continue_train=False, base=0, step='all', augment=False):

        if step == 'all':
            # Output is from last layer
            optimizer = self.optimizer
            loss_tensor = self.loss
            output_tensor_mean = tf.reduce_mean(self.step_output, 0)
            output_tensor_last = self.output
            output_tensor = self.output
        else:
            # Output is from step layer
            loss_tensor = tf.reduce_sum(tf.gather(self.step_loss, step))
            optimizer = tf.train.RMSPropOptimizer(self.lr).minimize(loss_tensor)  #, var_list=[self.step_var[i] for i in step])
            output_tensor_mean = tf.reduce_mean(tf.gather(self.step_output, step), 0)
            output_tensor_last = self.step_output[max(step)]

        config = tf.ConfigProto()
        config.gpu_options.allow_growth = True

        if augment:
            joints_lb = load_data.load_label(label_path + 'joints_LB.mat', 'joints_LB')
            joints_lt = load_data.load_label(label_path + 'joints_LT.mat', 'joints_LT')
            joints_rb = load_data.load_label(label_path + 'joints_RB.mat', 'joints_RB')
            joints_rt = load_data.load_label(label_path + 'joints_RT.mat', 'joints_RT')
            joints = [joints_lb, joints_lt, joints_rb, joints_rt]
            subset_name = ["_LB", "_LT", "_RB", "_RT"]
        else:
            joints = load_data.load_label(label_path + 'joints.mat', 'joints')

        num_data = 2000
        start_data = 0

        with tf.Session(config=config) as sess:

            tf.global_variables_initializer().run()
            if continue_train:
                latest = tf.train.latest_checkpoint(project_path + 'parameters/')
                self.saver.restore(sess, latest)

            plot_loss = []
            plot_accu = []
            plot_accu_last = []
            plot_step = []

            # Feed batch to train
            base = base if continue_train else 0
            for i in range(base, maxepoch):

                image = []
                label = []
                joints_batch = []
                if start_data > num_data - batch_size - 0:
                    start_data = 0

                # Load Image and Label
                for j in range(start_data, start_data+batch_size):
                    if augment:
                        # Randomly Select a Subset of Dataset
                        subset_num = np.random.randint(4)
                        # Load Image
                        next_image = load_data.load_image(image_path+subset_name[subset_num]+('\\%04d' % (j+1))+'.jpg')
                        image.append(next_image)
                        # Load Heatmap
                        next_heatmap = load_data.load_heatmap(label_path+('heatmap'+subset_name[subset_num]+'\\im%04d' % (j+1))+'.mat')
                        label.append(next_heatmap)
                        # Load Joints
                        joints_batch.append(joints[subset_num][j])
                    else:
                        # Load Image
                        next_image = load_data.load_image(image_path+('%04d' % (j+1))+'.jpg')
                        image.append(next_image)
                        # Load Heatmap
                        next_heatmap = load_data.load_heatmap(label_path+('heatmap\\im%04d' % (j+1))+'.mat')
                        label.append(next_heatmap)
                        # Load Joints
                        joints_batch.append(joints[j])
                start_data += batch_size

                # Optimization
                sess.run([optimizer], feed_dict={self.input: image, self.label: label})

                # Get Loss and Output(Prediction)
                loss, output, output_last = sess.run([loss_tensor, output_tensor_mean, output_tensor_last], feed_dict={self.input: image, self.label: label})
                max_ind = [[output[ii, :, :, jj].argmax() for jj in range(14)] for ii in range(batch_size)]
                max_ind_last = [[output_last[ii, :, :, jj].argmax() for jj in range(14)] for ii in range(batch_size)]

                joints_index = np.transpose(np.unravel_index(max_ind, [64, 64]), [1, 2, 0])
                joints_last = np.transpose(np.unravel_index(max_ind_last, [64, 64]), [1, 2, 0])

                # Calculate Accuracy
                count = 1e-5
                right = count
                right_last = count
                for b in range(batch_size):
                    for j in range(14):
                        if not joints_batch[b][j][2]:
                            count += 1
                            if np.abs(joints_index[b][j][0] - joints_batch[b][j][0]/4) < 3 and np.abs(joints_index[b][j][1] - joints_batch[b][j][1]/4) < 3:
                                right += 1
                            if np.abs(joints_last[b][j][0] - joints_batch[b][j][0]/4) < 3 and np.abs(joints_last[b][j][1] - joints_batch[b][j][1]/4) < 3:
                                right_last += 1
                accuracy = right / count
                accuracy_last = right_last / count
                print("Iteration: %5d | loss:%.8f | accuracy:%.6f | accuracy_last:%.6f" % (i, loss, accuracy, accuracy_last))

                if i % 1001 == 0:
                    visual.hotmap_visualization(output[0], 3, "image" + str(i),
                                                project_path + "visualization\\Visual_Image\\Step"
                                                + str(step) + "\\", raw_image=image[0])

                # Print Training Information
                if i % 200 == 0 and i != 0:
                    plot_loss.append(loss)
                    plot_accu.append(accuracy)
                    plot_accu_last.append(accuracy_last)
                    plot_step.append(len(plot_step))
                    load_data.plot_info(plot_loss, plot_accu, plot_accu_last, plot_step, name=str(step))
                    self.saver.save(sess, 'parameters/hourglass_model', global_step=i)

    def test(self, image_path, label_path):
        config = tf.ConfigProto()
        config.gpu_options.allow_growth = True

        image_list = sorted(os.listdir(image_path))
        joints = load_data.load_label(label_path+'joints', 'joints')

        num_data = len(image_list)

        with tf.Session(config=config) as sess:
            latest = tf.train.latest_checkpoint(project_path + 'parameters/')
            self.saver.restore(sess, latest)

            for i in range(num_data):
                # Get Image and Heatmap
                next_image = [load_data.load_image(image_path+('%04d' % (i+1))+'.jpg')]
                next_heatmap = [load_data.load_heatmap(label_path+('heatmap\\im%04d' % (i+1))+'.mat')]

                # Get Loss and Output(Prediction)
                loss, output = sess.run([self.loss, self.output], feed_dict={self.input: next_image, self.label: next_heatmap})
                output = np.squeeze(output)
                max_ind = [output[:, :, jj].argmax() for jj in range(14)]
                joints_index = np.transpose(np.unravel_index(max_ind, [64, 64]))

                # Visualization
                visual.hotmap_visualization(output, 3, "test"+str(i),
                                            project_path + "visualization\\Visual_Image\\test"
                                            +"\\", raw_image=next_image)

                # Calculate Accuracy
                count = 1e-5
                right = count
                for j in range(14):
                    if not joints[i][j][2]:
                        count += 1
                        if np.abs(joints_index[j][0] - joints[i][j][0]/4) < 3 and np.abs(joints_index[j][1] - joints[i][j][1]/4) < 3:
                            right += 1
                accuracy = right / count
                print("Image:%4d loss:%.8f accuracy:%.6f" % (i, loss, accuracy))
