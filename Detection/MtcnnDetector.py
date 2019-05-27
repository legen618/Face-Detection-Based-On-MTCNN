import cv2
import time
import numpy as np
import sys

sys.path.append("../")
from train_models.MTCNN_config import config
from Detection.nms import py_nms


class MtcnnDetector(object):

    def __init__(self,
                 detectors,
                 min_face_size=20,
                 stride=2,
                 threshold=[0.6, 0.7, 0.7],
                 scale_factor=0.79,
                 # scale_factor=0.709,#change
                 slide_window=False):

        self.pnet_detector = detectors[0]
        self.rnet_detector = detectors[1]
        self.onet_detector = detectors[2]
        self.min_face_size = min_face_size
        self.stride = stride
        self.thresh = threshold
        self.scale_factor = scale_factor
        self.slide_window = slide_window

    def convert_to_square(self, bbox):
        """
        把输入边框变成正方形状，以最长的边为基准，不改变中心点。
        Parameters:
        ----------
        bbox: numpy array
        
        Returns:
        -------
        square bbox
        """
        square_bbox = bbox.copy()

        h = bbox[:, 3] - bbox[:, 1] + 1
        w = bbox[:, 2] - bbox[:, 0] + 1
        max_side = np.maximum(h, w)
        square_bbox[:, 0] = bbox[:, 0] + w * 0.5 - max_side * 0.5
        square_bbox[:, 1] = bbox[:, 1] + h * 0.5 - max_side * 0.5
        square_bbox[:, 2] = square_bbox[:, 0] + max_side - 1
        square_bbox[:, 3] = square_bbox[:, 1] + max_side - 1
        return square_bbox

    def calibrate_box(self, bbox, reg):
        """
            calibrate bboxes
        Parameters:
        ----------
            bbox: numpy array, shape n x 5
                input bboxes
            reg:  numpy array, shape n x 4
                bboxes adjustment
        Returns:
        -------
            bboxes after refinement
        """

        bbox_c = bbox.copy()
        w = bbox[:, 2] - bbox[:, 0] + 1
        w = np.expand_dims(w, 1)
        h = bbox[:, 3] - bbox[:, 1] + 1
        h = np.expand_dims(h, 1)
        reg_m = np.hstack([w, h, w, h])
        aug = reg_m * reg
        bbox_c[:, 0:4] = bbox_c[:, 0:4] + aug
        return bbox_c


    def generate_bbox(self, cls_map, reg, scale, threshold):
        """
            generate bbox from feature cls_map according to the threshold.
        Parameters:
        ----------
            cls_map: numpy array , n x m
                detect score for each position
            reg: numpy array , n x m x 4
                bbox
            scale: float number
                scale of this detection
            threshold: float number
                detect threshold
        Returns:
        -------
            bbox array:[x1, y1, x2, y2, score, x1_offset, y1_offset, x2_offset, y2_offset]
            x and y are the coordinate of base anchor which unsampled from feature map.
            x和y都是根据特征图反采样得来的坐标，表示特征图这个点表达了原图哪个地方的特征  

            x1_offset and y1_offset are the prediction of PNet.
            x1_offset和y1_offset都是PNet的预测结果。
        """
        # 因为只有一个最大池化层，所以反采样只用乘以二就行了
        stride = 2
        # stride = 4
        cellsize = 12
        # cellsize = 25

        # index of class_prob larger than threshold
        t_index = np.where(cls_map > threshold)

        # find nothing
        if t_index[0].size == 0:
            return np.array([])
        # offset
        dx1, dy1, dx2, dy2 = [reg[t_index[0], t_index[1], i] for i in range(4)]

        reg = np.array([dx1, dy1, dx2, dy2])
        score = cls_map[t_index[0], t_index[1]]
        boundingbox = np.vstack([np.round((stride * t_index[1]) / scale),
                                 np.round((stride * t_index[0]) / scale),
                                 np.round((stride * t_index[1] + cellsize) / scale),
                                 np.round((stride * t_index[0] + cellsize) / scale),
                                 score,
                                 reg])

        return boundingbox.T

    # pre-process images
    def processed_image(self, img, scale):
        '''
            rescale/resize the image according to the scale by multiply width and height with scale
        Parameter
        ----------------------
            img: image
            scale: float
        Return
        --------------------
            resized image
        '''
        height, width, channels = img.shape
        new_height = int(height * scale)  # resized new height
        new_width = int(width * scale)  # resized new width
        new_dim = (new_width, new_height)
        img_resized = cv2.resize(img, new_dim, interpolation=cv2.INTER_LINEAR)  # resized image
        img_resized = (img_resized - 127.5) / 128
        return img_resized

    def pad(self, bboxes, w, h):
        """
            pad the the bboxes, also restrict the size of it
        Parameters:
        ----------
            bboxes: numpy array, n x 5
                input bboxes
            w: float number
                width of the input image
            h: float number
                height of the input image
        Returns :
        ------
            dy, dx : numpy array, n x 1
                start point of the bbox in target image
            edy, edx : numpy array, n x 1
                end point of the bbox in target image
            y, x : numpy array, n x 1
                start point of the bbox in original image
            ex, ex : numpy array, n x 1
                end point of the bbox in original image
            tmph, tmpw: numpy array, n x 1
                height and width of the bbox
        """
        tmpw, tmph = bboxes[:, 2] - bboxes[:, 0] + 1, bboxes[:, 3] - bboxes[:, 1] + 1
        num_box = bboxes.shape[0]

        dx, dy = np.zeros((num_box,)), np.zeros((num_box,))
        edx, edy = tmpw.copy() - 1, tmph.copy() - 1

        x, y, ex, ey = bboxes[:, 0], bboxes[:, 1], bboxes[:, 2], bboxes[:, 3]

        tmp_index = np.where(ex > w - 1) #找到candidate右边框超过图片的
        edx[tmp_index] = tmpw[tmp_index] + w - 2 - ex[tmp_index]
        ex[tmp_index] = w - 1

        tmp_index = np.where(ey > h - 1)
        edy[tmp_index] = tmph[tmp_index] + h - 2 - ey[tmp_index]
        ey[tmp_index] = h - 1

        tmp_index = np.where(x < 0)
        dx[tmp_index] = 0 - x[tmp_index]
        x[tmp_index] = 0

        tmp_index = np.where(y < 0)
        dy[tmp_index] = 0 - y[tmp_index]
        y[tmp_index] = 0

        # if dx[tmp_index] < 0 or dy[tmp_index] < 0:
        #     print("dx or dy is < 0")

        return_list = [dy, edy, dx, edx, y, ey, x, ex, tmpw, tmph]
        return_list = [item.astype(np.int32) for item in return_list]

        return return_list

    def detect_pnet(self, im):
        """Get face candidates through pnet

        Parameters:
        ----------
        im: numpy array
            input image array

        Returns:
        -------
        boxes: numpy array
            detected boxes before calibration
        boxes_c: numpy array n x 5 [x1, y1, x2, y2, score]
            boxes after calibration
        """
        net_size = 12

        current_scale = float(net_size) / self.min_face_size 
        # print("current_scale", net_size, self.min_face_size, current_scale)
        # risize image using current_scale
        im_resized = self.processed_image(im, current_scale)
        current_height, current_width, _ = im_resized.shape
        #print('current height and width:',current_height,current_width)
        # fcn
        all_boxes = list()
        while min(current_height, current_width) > net_size:
            # return the result predicted by pnet
            # cls_cls_map : H*w*2
            # reg: H*w*4
            # class_prob andd bbox_pred
            cls_cls_map, reg = self.pnet_detector.predict(im_resized) #用训练好的模型预测
            maxseses = cls_cls_map[:, :, 1]
            print(np.max(np.max(maxseses, axis=1)), np.argmax(np.max(maxseses, axis=1)), np.argmax(np.max(maxseses, axis=0)), np.max(cls_cls_map[:, :, 1], axis=1), current_height)
            # boxes: num*9(x1,y1,x2,y2,score,x1_offset,y1_offset,x2_offset,y2_offset)
            boxes = self.generate_bbox(cls_cls_map[:, :, 1], reg, current_scale, self.thresh[0])
            # scale_factor is 0.79 in default
            current_scale *= self.scale_factor
            im_resized = self.processed_image(im, current_scale)
            current_height, current_width, _ = im_resized.shape

            if boxes.size == 0:
                continue
            # get the index from non-maximum s
            keep = py_nms(boxes[:, :5], 0.5, 'Union')
            boxes = boxes[keep]
            all_boxes.append(boxes)

        if len(all_boxes) == 0:
            return None, None, None

        all_boxes = np.vstack(all_boxes)

        # merge the detection from first stage
        keep = py_nms(all_boxes[:, 0:5], 0.7, 'Union')
        all_boxes = all_boxes[keep]
        boxes = all_boxes[:, :5]
        
        # bounding_boxes' widthes and heights
        bbw = all_boxes[:, 2] - all_boxes[:, 0] + 1 
        bbh = all_boxes[:, 3] - all_boxes[:, 1] + 1

        # refine the boxes
        boxes_c = np.vstack([all_boxes[:, 0] + all_boxes[:, 5] * bbw,
                             all_boxes[:, 1] + all_boxes[:, 6] * bbh,
                             all_boxes[:, 2] + all_boxes[:, 7] * bbw,
                             all_boxes[:, 3] + all_boxes[:, 8] * bbh,
                             all_boxes[:, 4]])
        boxes_c = boxes_c.T

        return boxes, boxes_c, None

    def detect_rnet(self, im, dets):
        """Get face candidates using rnet

        Parameters:
        ----------
        im: numpy array
            input image array
        dets: numpy array
            detection results of pnet

        Returns:
        -------
        boxes: numpy array
            detected boxes before calibration
        boxes_c: numpy array
            boxes after calibration
        """
        h, w, c = im.shape
        dets = self.convert_to_square(dets)
        dets[:, 0:4] = np.round(dets[:, 0:4])

        [dy, edy, dx, edx, y, ey, x, ex, tmpw, tmph] = self.pad(dets, w, h)
        num_boxes = dets.shape[0]
        cropped_ims = np.zeros((num_boxes, 24, 24, 3), dtype=np.float32)
        for i in range(num_boxes):
            tmp = np.zeros((tmph[i], tmpw[i], 3), dtype=np.uint8)
            tmp[dy[i]:edy[i] + 1, dx[i]:edx[i] + 1, :] = im[y[i]:ey[i] + 1, x[i]:ex[i] + 1, :]
            cropped_ims[i, :, :, :] = (cv2.resize(tmp, (24, 24)) - 127.5) / 128
        # cls_scores : num_data*2
        # reg: num_data*4
        # landmark: num_data*10
        cls_scores, reg, _ = self.rnet_detector.predict(cropped_ims)
        cls_scores = cls_scores[:, 1]
        keep_inds = np.where(cls_scores > self.thresh[1])[0]
        if len(keep_inds) > 0:
            boxes = dets[keep_inds]
            boxes[:, 4] = cls_scores[keep_inds]
            reg = reg[keep_inds]
            # landmark = landmark[keep_inds]
        else:
            return None, None, None

        keep = py_nms(boxes, 0.6)
        boxes = boxes[keep]
        boxes_c = self.calibrate_box(boxes, reg[keep])
        return boxes, boxes_c, None

    def detect_onet(self, im, dets):
        """Get face candidates using onet

        Parameters:
        ----------
        im: numpy array
            input image array
        dets: numpy array
            detection results of rnet

        Returns:
        -------
        boxes: numpy array
            detected boxes before calibration
        boxes_c: numpy array
            boxes after calibration
        """
        h, w, c = im.shape
        dets = self.convert_to_square(dets)
        dets[:, 0:4] = np.round(dets[:, 0:4])
        [dy, edy, dx, edx, y, ey, x, ex, tmpw, tmph] = self.pad(dets, w, h)
        num_boxes = dets.shape[0]
        cropped_ims = np.zeros((num_boxes, 48, 48, 3), dtype=np.float32)
        for i in range(num_boxes):
            tmp = np.zeros((tmph[i], tmpw[i], 3), dtype=np.uint8)
            tmp[dy[i]:edy[i] + 1, dx[i]:edx[i] + 1, :] = im[y[i]:ey[i] + 1, x[i]:ex[i] + 1, :]
            cropped_ims[i, :, :, :] = (cv2.resize(tmp, (48, 48)) - 127.5) / 128

        cls_scores, reg, landmark = self.onet_detector.predict(cropped_ims)
        # prob belongs to face
        cls_scores = cls_scores[:, 1]
        keep_inds = np.where(cls_scores > self.thresh[2])[0]
        if len(keep_inds) > 0:
            # pickout filtered box
            boxes = dets[keep_inds]
            boxes[:, 4] = cls_scores[keep_inds]
            reg = reg[keep_inds]
            landmark = landmark[keep_inds]
        else:
            return None, None, None

        # width
        w = boxes[:, 2] - boxes[:, 0] + 1
        # height
        h = boxes[:, 3] - boxes[:, 1] + 1
        landmark[:, 0::2] = (np.tile(w, (5, 1)) * landmark[:, 0::2].T + np.tile(boxes[:, 0], (5, 1)) - 1).T
        landmark[:, 1::2] = (np.tile(h, (5, 1)) * landmark[:, 1::2].T + np.tile(boxes[:, 1], (5, 1)) - 1).T
        boxes_c = self.calibrate_box(boxes, reg)

        boxes = boxes[py_nms(boxes, 0.6, "Minimum")]
        keep = py_nms(boxes_c, 0.6, "Minimum")
        boxes_c = boxes_c[keep]
        landmark = landmark[keep]
        return boxes, boxes_c, landmark

    # use for video
    def detect(self, img):
        """Detect face over image
        """
        boxes = None
        t = time.time()

        # pnet
        t1 = 0
        if self.pnet_detector:
            boxes, boxes_c, _ = self.detect_pnet(img)
            if boxes_c is None:
                return np.array([]), np.array([])

            t1 = time.time() - t
            t = time.time()

        # rnet
        t2 = 0
        if self.rnet_detector:
            boxes, boxes_c, _ = self.detect_rnet(img, boxes_c)
            if boxes_c is None:
                return np.array([]), np.array([])

            t2 = time.time() - t
            t = time.time()

        # onet
        t3 = 0
        if self.onet_detector:
            boxes, boxes_c, landmark = self.detect_onet(img, boxes_c)
            if boxes_c is None:
                return np.array([]), np.array([])

            t3 = time.time() - t
            t = time.time()
            # print(
            #    "time cost " + '{:.3f}'.format(t1 + t2 + t3) + '  pnet {:.3f}  rnet {:.3f}  onet {:.3f}'.format(t1, t2,
            #                                                                                                  t3))

        return boxes_c, landmark

    def detect_face(self, imgs_path, pnet_detections=None, rnet_detections=None):
        all_boxes = []  # save each image's bboxes
        landmarks = []
        # batch_idx = 0

        sum_time = 0
        t1_sum = 0
        t2_sum = 0
        t3_sum = 0
        num_of_img = len(imgs_path) #12880
        empty_array = np.array([])
        # test_data is iter_
        s_time = time.time()
        for i, img_path in enumerate(imgs_path):
            # databatch就是一张图片
            if i % 100 == 0 and i > 0:
                c_time = (time.time() - s_time )/100
                print("%d out of %d images done" % (i ,num_of_img))
                print('%f seconds for each image' % c_time)
                s_time = time.time()


            im = cv2.imread(img_path)
            # pnet
            if self.pnet_detector and pnet_detections is None: # detector[0]
                st = time.time()
                # ignore landmark
                _, boxes_c, _ = self.detect_pnet(im)

                t1 = time.time() - st
                sum_time += t1
                t1_sum += t1
                if boxes_c is None:
                    print("pnet: boxes_c is None...")
                    all_boxes.append(empty_array)
                    # pay attention
                    landmarks.append(empty_array)

                    continue
                #print(all_boxes)

            # rnet
            if self.rnet_detector and rnet_detections is None:
                if pnet_detections is not None:
                    boxes_c = pnet_detections[i]
                    if boxes_c == empty_array:
                        continue
                t = time.time()
                # ignore landmark
                _, boxes_c, _ = self.detect_rnet(im, boxes_c)
                t2 = time.time() - t
                sum_time += t2
                t2_sum += t2
                if boxes_c is None:
                    print("rnet: boxes_c is None...")
                    all_boxes.append(empty_array)
                    landmarks.append(empty_array)

                    continue
            
            # onet
            if self.onet_detector:
                if rnet_detections is not None:
                    boxes_c = rnet_detections[i]
                    if boxes_c == empty_array:
                        continue
                t = time.time()
                _, boxes_c, landmark = self.detect_onet(im, boxes_c)
                t3 = time.time() - t
                sum_time += t3
                t3_sum += t3
                if boxes_c is None:
                    print("onet: boxes_c is None...")
                    all_boxes.append(empty_array)
                    landmarks.append(empty_array)

                    continue

            all_boxes.append(boxes_c)
            landmark = [1]
            # landmarks.append(landmark)

            
        print('num of images', num_of_img)
        print("time cost in average" +
            '{:.3f}'.format(sum_time/num_of_img) +
            '  pnet {:.3f}  rnet {:.3f}  onet {:.3f}'.format(t1_sum/num_of_img, t2_sum/num_of_img,t3_sum/num_of_img))


        # num_of_data*9,num_of_data*10
        print('boxes length:',len(all_boxes))
        return all_boxes, landmarks

    def detect_single_image(self, im):
        all_boxes = []  # save each image's bboxes

        landmarks = []

       # sum_time = 0

        t1 = 0
        if self.pnet_detector:
          #  t = time.time()
            # ignore landmark
            boxes, boxes_c, landmark = self.detect_pnet(im)
           # t1 = time.time() - t
           # sum_time += t1
            if boxes_c is None:
                print("boxes_c is None...")
                all_boxes.append(np.array([]))
                # pay attention
                landmarks.append(np.array([]))


        # rnet

        if boxes_c is None:
            print('boxes_c is None after Pnet')
        t2 = 0
        if self.rnet_detector and not boxes_c is  None:
           # t = time.time()
            # ignore landmark
            boxes, boxes_c, landmark = self.detect_rnet(im, boxes_c)
           # t2 = time.time() - t
           # sum_time += t2
            if boxes_c is None:
                all_boxes.append(np.array([]))
                landmarks.append(np.array([]))


        # onet
        t3 = 0
        if boxes_c is None:
            print('boxes_c is None after Rnet')

        if self.onet_detector and not boxes_c is  None:
          #  t = time.time()
            boxes, boxes_c, landmark = self.detect_onet(im, boxes_c)
         #   t3 = time.time() - t
          #  sum_time += t3
            if boxes_c is None:
                all_boxes.append(np.array([]))
                landmarks.append(np.array([]))


        #print(
         #   "time cost " + '{:.3f}'.format(sum_time) + '  pnet {:.3f}  rnet {:.3f}  onet {:.3f}'.format(t1, t2, t3))

        all_boxes.append(boxes_c)
        landmarks.append(landmark)

        return all_boxes, landmarks
