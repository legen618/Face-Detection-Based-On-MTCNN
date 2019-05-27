import os, random
import tensorflow as tf
import cv2
import numpy as np
import time, sys, os
import matplotlib.pyplot as plt


def load_and_get_normalization_img(path, size=12):
    image = tf.io.read_file(path)
    image = tf.image.decode_jpeg(image, channels=3)
    image = tf.image.resize(image, [size, size])
    image = (image - 127.5) / 128.0  # normalize to [0,1] range
    return image


def get_dataset(path, batch_size=256, ratios=[1, 3, 1, 1]):
    """
    get all info from merged imglist and shuffle it.  
    获取所有合并了的训练图片信息并且打乱
    Parameter
    --------------------
        path: path of data source.
        batch_size
        ratios: [pos_ratio, neg_ratio, part_ratio, landmark_ratio]

    Return
    --------------------
        tuple: (num of samples, dataset)
    """
    net = path[-4:]
    if net == "PNet":
        size = 12
    elif net == "RNet":
        size = 24
    elif net == "ONet":
        size = 48
    else:
        print("unknown net: ", net)
        exit(-1)

    item = 'train_%s_landmark.txt' % net
    dataset_dir = os.path.join(path, item)

    imagelist = open(dataset_dir, 'r')

    all_image_paths = []
    all_image_labels = []
    all_image_bboxes = []
    all_image_landmarks = []

    pos_lines = []
    neg_lines = []
    part_lines = []
    landmark_lines = []

    lines = imagelist.readlines()

    for line in lines:
        info = line.strip().split(' ')
        if int(info[1]) == 1:
            pos_lines.append(line)
        elif int(info[1]) == 0:
            neg_lines.append(line)
        elif int(info[1]) == -1:
            part_lines.append(line)
        elif int(info[1]) == -2:
            landmark_lines.append(line)
        else:
            print("unknown label.")
            exit(-1)
    print("There are {} pos samples, {} neg samples, {} part samples and {} landmark samples \
before keeping ratios. {} samples in total".format(len(pos_lines),
                                                   len(neg_lines), 
                                                   len(part_lines), 
                                                   len(landmark_lines),
                                                   len(lines)))
    base_num = min(len(pos_lines), len(neg_lines), len(part_lines), len(landmark_lines))
    pos_num = ratios[0] * base_num
    neg_num = ratios[1] * base_num
    part_num = ratios[2] * base_num
    landmark_num = ratios[3] * base_num    

    random.shuffle(pos_lines)
    random.shuffle(neg_lines)
    random.shuffle(part_lines)
    random.shuffle(landmark_lines)

    shuffled_lines = pos_lines[:pos_num] + neg_lines[:neg_num] + part_lines[:part_num] + landmark_lines[:landmark_num]
    random.shuffle(shuffled_lines)

    for line in shuffled_lines:
        info = line.strip().split(' ')
        all_image_paths.append(info[0])
        all_image_labels.append(float(info[1]))
        if len(info) == 6:
            all_image_bboxes.append((float(info[2]), float(info[3]), float(info[4]), float(info[5])))
            all_image_landmarks.append((0., 0., 0., 0., 0., 0., 0., 0., 0., 0.))
        elif len(info) == 12:
            all_image_bboxes.append((0., 0., 0., 0.))
            all_image_landmarks.append((float(info[2]), float(info[3]), float(info[4]), float(info[5]), 
                                        float(info[6]), float(info[7]), float(info[8]), float(info[9]),
                                        float(info[10]), float(info[11])
                                        ))
        else:
            all_image_bboxes.append((0., 0., 0., 0.))
            all_image_landmarks.append((0., 0., 0., 0., 0., 0., 0., 0., 0., 0.))

    print("There are {} pos samples, {} neg samples, {} part samples and {} landmark samples \
after keeping ratios. {} samples in total".format(all_image_labels.count(1), 
                                                  all_image_labels.count(0), 
                                                  all_image_labels.count(-1), 
                                                  all_image_labels.count(-2),
                                                  len(shuffled_lines)))

    def preprocess_image(image):
        image = tf.image.decode_jpeg(image, channels=3)
        image = tf.image.resize(image, [size, size])
        image = (image - 127.5) / 128.0  # normalize to [-1,1] range
        return image

    def load_and_preprocess_image(path):
        image = tf.io.read_file(path)
        return preprocess_image(image)
        # return tf.zeros((12, 12, 3))

    path_ds = tf.data.Dataset.from_tensor_slices(all_image_paths)
    # print(path_ds)
    image_ds = path_ds.map(load_and_preprocess_image, num_parallel_calls=tf.data.experimental.AUTOTUNE) 
    label_ds = tf.data.Dataset.from_tensor_slices(all_image_labels)
    bbox_ds = tf.data.Dataset.from_tensor_slices(all_image_bboxes)
    landmark_ds = tf.data.Dataset.from_tensor_slices(all_image_landmarks)
    target_ds = tf.data.Dataset.zip((label_ds, bbox_ds, landmark_ds))

    image_label_bbox_landmarks_ds = tf.data.Dataset.zip((image_ds, target_ds))
    # print(image_label_bbox_landmarks_ds)

    ds = image_label_bbox_landmarks_ds.cache()
    ds = ds.shuffle(buffer_size=10000)
    # ds = ds.repeat()
    ds = ds.batch(batch_size)
    ds = ds.prefetch(buffer_size=tf.data.experimental.AUTOTUNE)
    print("get dataset done.")

    return len(all_image_paths), ds


def random_flip_images(image_batch,label_batch,landmark_batch):
    """
        for each batch, do flip or not flip operation randomly for data augment.
    Return
    --------------
        image_batch, landmark_batch
    """
    if random.choice([0,1]) > 0:
        fliplandmarkindexes = np.where(label_batch==-2)[0]
        flipposindexes = np.where(label_batch==1)[0]
        #only flip
        flipindexes = np.concatenate((fliplandmarkindexes,flipposindexes))
        # horizontal flip
        for i in flipindexes:
            cv2.flip(image_batch[i],1,image_batch[i])        
        
        #pay attention: flip landmark    
        for i in fliplandmarkindexes:
            landmark_ = landmark_batch[i].reshape((-1,2))
            landmark_ = np.asarray([(1-x, y) for (x, y) in landmark_])
            landmark_[[0, 1]] = landmark_[[1, 0]]#left eye<->right eye
            landmark_[[3, 4]] = landmark_[[4, 3]]#left mouth<->right mouth        
            landmark_batch[i] = landmark_.ravel()
        
    return image_batch,landmark_batch

def image_color_distort(inputs):
    inputs = tf.image.random_contrast(inputs, lower=0.5, upper=1.5)
    inputs = tf.image.random_brightness(inputs, max_delta=0.2)
    inputs = tf.image.random_hue(inputs,max_delta= 0.2)
    inputs = tf.image.random_saturation(inputs,lower = 0.5, upper= 1.5)
    return inputs





if __name__ == "__main__":
    tf.enable_eager_execution()
    assert(tf.executing_eagerly)

    num, dataset = get_dataset("../data/imglists/PNet")
    for image, target in dataset.take(1):
        plt.figure()
        plt.imshow(image)
        plt.show()
