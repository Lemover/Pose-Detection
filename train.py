from model.hourglass_net import Stacked_Hourglass

block_number = 8
layers = 3
lr = 2e-4
out_dim = 256
point_num = 14
maxepoch = 300001
dropout_rate = 0.2

image_path = 'D:\\CS\\机器学习大作业\\Pose-Detection\\data_set\\images_padding\\'
label_path = 'D:\\CS\\机器学习大作业\\Pose-Detection\\data_set\\label\\'
batch_size = 1

model = Stacked_Hourglass(block_number=block_number, layers=layers, out_dim=out_dim, point_num=point_num, lr=lr, training=True, dropout_rate=dropout_rate)
model.train(image_path, label_path, batch_size, maxepoch, False)
