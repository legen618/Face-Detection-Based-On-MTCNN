#coding:utf-8
import tensorflow as tf
from tensorflow import keras
from keras.utils import plot_model
import numpy as np
num_keep_radio = 0.7

#cls_prob:batch*2
#label:batch

def cls_ohem(cls_prob, label):
    zeros = tf.zeros_like(label) #全初始化为0，形状和label一样
    #label=-1 --> label=0net_factory

    #pos -> 1, neg -> 0, others -> 0
    label_filter_invalid = tf.where(tf.less(label,0), zeros, label) # 若label中的值小于等于0，则为0，否则为1，就是把label中-1变为0
    num_cls_prob = tf.size(cls_prob) #[384, 2] ---> 768
    cls_prob_reshape = tf.reshape(cls_prob,[num_cls_prob,-1]) #---->[768, 1]
    label_int = tf.cast(label_filter_invalid,tf.int32)
    # get the number of rows of class_prob
    num_row = tf.to_int32(cls_prob.get_shape()[0]) #384
    #row = [0,2,4.....]
    row = tf.range(num_row)*2
    indices_ = row + label_int # 就是如果label是pos就看1X1X2中的第2个，neg或part就看第1个
    # indices_ = row + 1
    label_prob = tf.squeeze(tf.gather(cls_prob_reshape, indices_)) #从cls_prob_reshape中获取索引为indices_的值，squeeze后变成一维的[384即batch_size]
    loss = -tf.log(label_prob+1e-10) # 参考https://blog.csdn.net/weixin_34204722/article/details/87327239
    zeros = tf.zeros_like(label_prob, dtype=tf.float32)
    ones = tf.ones_like(label_prob,dtype=tf.float32)
    # set pos and neg to be 1, rest to be 0
    valid_inds = tf.where(label < zeros,zeros,ones)
    # get the number of POS and NEG examples
    num_valid = tf.reduce_sum(valid_inds)

    keep_num = tf.cast(num_valid*num_keep_radio,dtype=tf.int32)
    #FILTER OUT PART AND LANDMARK DATA
    loss = loss * valid_inds
    loss,_ = tf.nn.top_k(loss, k=keep_num)
    return tf.reduce_mean(loss)


#label=1 or label=-1 then do regression
def bbox_ohem(bbox_pred,bbox_target,label):
    '''

    :param bbox_pred:
    :param bbox_target:
    :param label: class label
    :return: mean euclidean loss for all the pos and part examples
    '''
    zeros_index = tf.zeros_like(label, dtype=tf.float32)
    ones_index = tf.ones_like(label,dtype=tf.float32)
    # keep pos and part examples
    valid_inds = tf.where(tf.equal(tf.abs(label), 1),ones_index,zeros_index) # 等于±1的有效为1，不等于1的无效为0，即筛选出pos和part的索引
    #(batch,)
    #calculate square sum
    square_error = tf.square(bbox_pred-bbox_target)
    square_error = tf.reduce_sum(square_error,axis=1)
    #keep_num scalar
    num_valid = tf.reduce_sum(valid_inds)
    #keep_num = tf.cast(num_valid*num_keep_radio,dtype=tf.int32)
    # count the number of pos and part examples
    keep_num = tf.cast(num_valid, dtype=tf.int32)
    #keep valid index square_error
    square_error = square_error*valid_inds
    # keep top k examples, k equals to the number of positive examples
    _, k_index = tf.nn.top_k(square_error, k=keep_num)
    square_error = tf.gather(square_error, k_index)

    return tf.reduce_mean(square_error)

def landmark_ohem(landmark_pred,landmark_target,label):
    '''

    :param landmark_pred:
    :param landmark_target:
    :param label:
    :return: mean euclidean loss
    '''
    #keep label =-2  then do landmark detection
    ones = tf.ones_like(label,dtype=tf.float32)
    zeros = tf.zeros_like(label,dtype=tf.float32)
    valid_inds = tf.where(tf.equal(label,-2),ones,zeros)
    square_error = tf.square(landmark_pred-landmark_target)
    square_error = tf.reduce_sum(square_error,axis=1)
    num_valid = tf.reduce_sum(valid_inds) # 0
    #keep_num = tf.cast(num_valid*num_keep_radio,dtype=tf.int32)
    keep_num = tf.cast(num_valid, dtype=tf.int32) # 0
    square_error = square_error*valid_inds
    _, k_index = tf.nn.top_k(square_error, k=keep_num)
    square_error = tf.gather(square_error, k_index)
    # mse = tf.reduce_mean(square_error)
    return tf.reduce_mean(square_error) # 当square_error为空时会出现nan bug
    
def cal_accuracy(cls_prob,label):
    '''

    :param cls_prob:
    :param label:
    :return:calculate classification accuracy for pos and neg examples only
    '''
    # get the index of maximum value along axis one from cls_prob
    # 0 for negative 1 for positive
    #pred = cls_prob[:, 1]# 
    pred = tf.argmax(cls_prob,axis=1)
    label_int = tf.cast(label,tf.int64)
    # return the index of pos and neg examples
    cond = tf.where(tf.greater_equal(label_int,0))
    picked = tf.squeeze(cond)
    # gather the label of pos and neg examples
    label_picked = tf.gather(label_int,picked)
    pred_picked = tf.gather(pred,picked)
    #calculate the mean value of a vector contains 1 and 0, 1 for correct classification, 0 for incorrect
    # ACC = (TP+FP)/total population
    accuracy_op = tf.reduce_mean(tf.cast(tf.equal(label_picked,pred_picked),tf.float32))
    return accuracy_op

class P_Net(keras.Model):
    def __init__(self):
        super(P_Net, self).__init__(name="P_Net")
        # Define layers here.
        self.conv1 = keras.layers.Conv2D(10, (3, 3), name="conv1", kernel_regularizer=keras.regularizers.l2(0.0005))
        self.prelu1 = keras.layers.PReLU(tf.constant_initializer(0.25), shared_axes=[1, 2], name="prelu1")
        self.pool1 = keras.layers.MaxPooling2D((2, 2), name="pool1")
        self.conv2 = keras.layers.Conv2D(16, (3, 3), name="conv2", kernel_regularizer=keras.regularizers.l2(0.0005))
        self.prelu2 = keras.layers.PReLU(tf.constant_initializer(0.25), shared_axes=[1, 2], name="prelu2")
        self.conv3 = keras.layers.Conv2D(32, (3, 3), name="conv3", kernel_regularizer=keras.regularizers.l2(0.0005))
        self.prelu3 = keras.layers.PReLU(tf.constant_initializer(0.25), shared_axes=[1, 2], name="prelu3")
        self.cls_output = keras.layers.Conv2D(2, (1, 1), activation="softmax", name="conv4_1")
        self.bbox_pred = keras.layers.Conv2D(4, (1, 1), name="conv4_2")
        self.landmark_pred = keras.layers.Conv2D(10, (1, 1), name="conv4_3")

    def call(self, inputs):
        # Define your forward pass here,
        # using layers you previously defined (in `__init__`).
        x = self.conv1(inputs)
        x = self.prelu1(x)
        x = self.pool1(x)
        x = self.conv2(x)
        x = self.prelu2(x)
        x = self.conv3(x)
        x = self.prelu3(x)
        return [self.cls_output(x), self.bbox_pred(x), self.landmark_pred(x)]

    def get_summary(self, input_shape):
        inputs = keras.Input(input_shape)
        model = keras.Model(inputs, self.call(inputs))
        print(model.summary())


class R_Net(keras.Model):
    def __init__(self):
        super(R_Net, self).__init__(name="R_Net")
        # Define layers here.
        self.conv1 = keras.layers.Conv2D(28, (3, 3), name="conv1")
        self.prelu1 = keras.layers.PReLU(tf.constant_initializer(0.25), shared_axes=[1, 2], name="prelu1")
        self.pool1 = keras.layers.MaxPooling2D((3, 3), 2, padding="same", name="pool1")
        self.conv2 = keras.layers.Conv2D(48, (3, 3), name="conv2")
        self.prelu2 = keras.layers.PReLU(tf.constant_initializer(0.25), shared_axes=[1, 2], name="prelu2")
        self.pool2 = keras.layers.MaxPooling2D((3, 3), 2, padding="valid", name="pool2")
        self.conv3 = keras.layers.Conv2D(64, (2, 2), name="conv3")
        self.prelu3 = keras.layers.PReLU(tf.constant_initializer(0.25), shared_axes=[1, 2], name="prelu3")
        self.flatten = keras.layers.Flatten()
        self.fc1 = keras.layers.Dense(128, name="fc1")
        self.prelu4 = keras.layers.PReLU(tf.constant_initializer(0.25), name="prelu4")
        self.dropout = keras.layers.Dropout(0.5, name="dropout1")
        self.cls_prob = keras.layers.Dense(2, activation="softmax", name="cls_fc")
        self.bbox_pred = keras.layers.Dense(4, name="bbox_fc")
        self.landmark_pred = keras.layers.Dense(10, name="landmark_fc")

    def call(self, inputs, training=False):
        # Define your forward pass here,
        # using layers you previously defined (in `__init__`).
        x = self.conv1(inputs)
        x = self.prelu1(x)
        x = self.pool1(x)
        x = self.conv2(x)
        x = self.prelu2(x)
        x = self.pool2(x)
        x = self.conv3(x)
        x = self.prelu3(x)
        x = self.flatten(x)
        x = self.fc1(x)
        x = self.prelu4(x)
        if training:
            x = self.dropout(x)
        return [self.cls_prob(x), self.bbox_pred(x), self.landmark_pred(x)]

    def get_summary(self, input_shape):
        inputs = keras.Input(input_shape)
        model = keras.Model(inputs, self.call(inputs))
        print(model.summary())


class O_Net(keras.Model):
    def __init__(self):
        super(O_Net, self).__init__(name="O_Net")
        # Define layers here.
        self.conv1 = keras.layers.Conv2D(32, (3, 3), name="conv1")
        self.prelu1 = keras.layers.PReLU(tf.constant_initializer(0.25), shared_axes=[1, 2], name="prelu1")
        self.pool1 = keras.layers.MaxPooling2D((3, 3), 2, padding="same", name="pool1")
        self.conv2 = keras.layers.Conv2D(64, (3, 3), name="conv2")
        self.prelu2 = keras.layers.PReLU(tf.constant_initializer(0.25), shared_axes=[1, 2], name="prelu2")
        self.pool2 = keras.layers.MaxPooling2D((3, 3), 2, name="pool2")
        self.conv3 = keras.layers.Conv2D(64, (3, 3), name="conv3")
        self.prelu3 = keras.layers.PReLU(tf.constant_initializer(0.25), shared_axes=[1, 2], name="prelu3") 
        self.pool3 = keras.layers.MaxPooling2D((2, 2), 2, padding="same", name="pool3")
        self.conv4 = keras.layers.Conv2D(128, (2, 2), name="conv4")
        self.prelu4 = keras.layers.PReLU(tf.constant_initializer(0.25), shared_axes=[1, 2], name="prelu4") 
        self.flatten = keras.layers.Flatten()
        self.fc1 = keras.layers.Dense(256, name="fc1")
        self.prelu5 = keras.layers.PReLU(tf.constant_initializer(0.25), name="prelu5") 
        self.dropout = keras.layers.Dropout(0.5, name="dropout1")
        self.cls_prob = keras.layers.Dense(2, activation="softmax", name="cls_fc")
        self.bbox_pred = keras.layers.Dense(4, name="bbox_fc")
        self.landmark_pred = keras.layers.Dense(10, name="landmark_fc")


    def call(self, inputs, training=False):
        # Define your forward pass here,
        # using layers you previously defined (in `__init__`).
        x = self.conv1(inputs)
        x = self.prelu1(x)
        x = self.pool1(x)
        x = self.conv2(x)
        x = self.prelu2(x)
        x = self.pool2(x)
        x = self.conv3(x)
        x = self.prelu3(x)
        x = self.pool3(x)
        x = self.conv4(x)
        x = self.prelu4(x)
        x = self.flatten(x)
        x = self.fc1(x)
        x = self.prelu5(x)
        if training:
            x = self.dropout(x)
        return [self.cls_prob(x), self.bbox_pred(x), self.landmark_pred(x)]

    def get_summary(self, input_shape):
        inputs = keras.Input(input_shape)
        model = keras.Model(inputs, self.call(inputs))
        print(model.summary())

if __name__ == "__main__":
    tf.enable_eager_execution()
    p_net = P_Net()
    r_net = R_Net()
    o_net = O_Net()
    o_net.get_summary((48, 48, 3))

    plot_model(p_net, to_file="C:/Users/dove/Desktop/pnet.png")

    # p_net.build((12, 12, 3))
    # p_net.get_summary((24, 24, 3))
    # print(p_net.trainable_variables)

