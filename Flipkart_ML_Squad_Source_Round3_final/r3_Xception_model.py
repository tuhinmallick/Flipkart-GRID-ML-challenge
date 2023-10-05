# -*- coding: utf-8 -*-
"""
Created on Sun Feb 10 06:06:22 2019

@author: Anoubhav
"""

# Importing libraries
import os
import numpy as np
np.random.seed(42) 
import pandas as pd
from sklearn.utils import shuffle
import csv
import math
from PIL import Image
import numpy as np
import os
from tensorflow.keras import layers
from tensorflow.keras import Model
import glob
import cv2
from tensorflow.keras.applications.xception import Xception, preprocess_input
from tensorflow.keras.callbacks import ModelCheckpoint, EarlyStopping, ReduceLROnPlateau, Callback
from tensorflow.keras.layers import Input, Dense, GlobalAveragePooling2D, Flatten
from tensorflow.keras.utils import Sequence
from tensorflow.keras.backend import epsilon



TRAIN_PATH = 'training_set.csv'
TEST_PATH = 'test.csv'


# Ran for 127 epochs.... once again got 89 acc.
IMAGE_SIZE = (160, 120)

IMAGES = "test_images/*png"

# For source file submission they need not run for 128 epochs, 78 is just fine
EPOCHS = 128
BATCH_SIZE = 24
PATIENCE = 30

TRAIN_CSV = "train_xcep.csv"
VALIDATION_CSV = "val_xcep.csv"

NUM_CLASSES = 4

# Creates folder for storing model checkpoints
newpath = os.path.join(os.getcwd(), 'r3_Xception_checkpoints')
if not os.path.exists(newpath):
    os.makedirs(newpath)

def create_train_val_csv(seed = 42, train_val_split = 0.2):
    df = pd.read_csv(TRAIN_PATH)
    df['height'] = 480
    df['width']  = 640
    df = df[['image_name', 'height', 'width', 'x1', 'y1', 'x2', 'y2']]
    df['image_name'] = 'train_images/' + df['image_name']
    
    df = df.set_index('image_name')

    df = shuffle(df, random_state = seed)

    row_no = int(df.shape[0]*train_val_split)

    df_val   = df.iloc[ : row_no, :]
    df_train = df.iloc[row_no : , :]

    df_train.to_csv('train_xcep.csv', index = True, header = False)
    df_val.to_csv('val_xcep.csv', index = True, header = False)
    
    del df, df_val, df_train
    
def get_predictions():
    model = create_model()
    
    # Path of directory containing all model checkpoints
    path = os.path.join(os.getcwd(), 'r3_Xception_checkpoints')


#   Filename format: model-1-{epoch:02d}-{val_iou:.2f}-.h5

    # Finds the checkpoint with lowest val_loss. This checkpoint is loaded to model.
    max_iou = 0   # arbitrary large number
    min_filename = ''
    min_epoch = 0
    for file in os.listdir(path):
        if file.split('-')[1] == '1':
            temp = file.split('-')[3]
            epoch = int(file.split('-')[2])
            if float(temp) >= max_iou and epoch>min_epoch:
                max_iou = float(temp)
                min_filename = file
                min_epoch = epoch
            
    # Load model weights        
    model.load_weights(os.path.join(path, min_filename))
    print('Model loaded')
    
    test = pd.read_csv(TEST_PATH, index_col='image_name')
    
    count = 0
    for filename in glob.glob(IMAGES):
        if count%1000==0: print('Number of images predicted:', count)
        count += 1
        unscaled = cv2.imread(filename)
        # image_height, image_width, _ = unscaled.shape
        image_height, image_width = 480, 640
        try:
            image = cv2.resize(unscaled, (IMAGE_SIZE[1], IMAGE_SIZE[0]))
            feat_scaled = preprocess_input(np.array(image, dtype=np.float32))
    
            region = model.predict(x=np.array([feat_scaled]))[0]
    
            x1 = int(region[0] * image_width / IMAGE_SIZE[0])
            y1 = int(region[1] * image_height / IMAGE_SIZE[1])
    
            x2 = int((region[0] + region[2]) * image_width / IMAGE_SIZE[0])
            y2 = int((region[1] + region[3]) * image_height / IMAGE_SIZE[1])
            
#            filename contains test_images/ which is not there in test.csv
            test.loc[filename[12:], 'x1'] = x1
            test.loc[filename[12:], 'x2'] = x2
            test.loc[filename[12:], 'y1'] = y1
            test.loc[filename[12:], 'y2'] = y2
        except:
            print(count, filename)
    
    test.to_csv('predictions_r3_xcep_model1.csv', encoding='utf-8', index=True)
    
    
class DataGenerator(Sequence):

    def __init__(self, csv_file):
        self.paths = []

        with open(csv_file, "r") as file:
            self.coords = np.zeros((sum(1 for _ in file), 4))
            file.seek(0)

            reader = csv.reader(file, delimiter=",")
            for index, row in enumerate(reader):
                for i, r in enumerate(row[1:7]):
                    row[i+1] = int(r)
                path, image_height, image_width, x0, y0, x1, y1 = row
                self.coords[index, 0] = x0 * IMAGE_SIZE[0] / image_width
                self.coords[index, 1] = y0 * IMAGE_SIZE[1] / image_height
                self.coords[index, 2] = (x1 - x0) * IMAGE_SIZE[0] / image_width
                self.coords[index, 3] = (y1 - y0) * IMAGE_SIZE[1] / image_height 
                self.paths.append(path)

    def __len__(self):
        return math.ceil(len(self.coords) / BATCH_SIZE)

    def __getitem__(self, idx):
        batch_paths = self.paths[idx * BATCH_SIZE:(idx + 1) * BATCH_SIZE]
        batch_coords = self.coords[idx * BATCH_SIZE:(idx + 1) * BATCH_SIZE]

        batch_images = np.zeros((len(batch_paths), IMAGE_SIZE[0], IMAGE_SIZE[1], 3), dtype=np.float32)
        for i, f in enumerate(batch_paths):
            img = Image.open(f)
            img = img.resize((IMAGE_SIZE[1], IMAGE_SIZE[0]))
            img = img.convert('RGB')
            batch_images[i] = preprocess_input(np.array(img, dtype=np.float32))
            img.close()

        return batch_images, batch_coords

    
class Validation(Callback):
    def __init__(self, generator):
        self.generator = generator

    def on_epoch_end(self, epoch, logs):
        mse = 0
        intersections = 0
        unions = 0

        for i in range(len(self.generator)):
            batch_images, gt = self.generator[i]
            pred = self.model.predict_on_batch(batch_images)
            mse += np.linalg.norm(gt - pred, ord='fro') / pred.shape[0]

            pred = np.maximum(pred, 0)

            diff_width = np.minimum(gt[:,0] + gt[:,2], pred[:,0] + pred[:,2]) - np.maximum(gt[:,0], pred[:,0])
            diff_height = np.minimum(gt[:,1] + gt[:,3], pred[:,1] + pred[:,3]) - np.maximum(gt[:,1], pred[:,1])
            intersection = np.maximum(diff_width, 0) * np.maximum(diff_height, 0)

            area_gt = gt[:,2] * gt[:,3]
            area_pred = pred[:,2] * pred[:,3]
            union = np.maximum(area_gt + area_pred - intersection, 0)

            intersections += np.sum(intersection * (union > 0))
            unions += np.sum(union)

        iou = np.round(intersections / (unions + epsilon()), 4)
        logs["val_iou"] = iou

        mse = np.round(mse, 4)
        logs["val_mse"] = mse

        print(f" - val_iou: {iou} - val_mse: {mse}")

def create_model():
    # Image shape
    image_input = Input(shape=(160, 120, 3))

    # Set weights to none. Remove dense layers of model
    model = Xception(input_tensor=image_input, include_top=False, weights=None)

    # Add custom fully connected layers
    last_layer = model.get_layer('block14_sepconv2_act').output
    x= GlobalAveragePooling2D()(last_layer)
    x = Dense(512, activation='relu', name='fc1')(x)
    x = Dense(128, activation='relu', name='fc2')(x)
    out = Dense(NUM_CLASSES, activation='linear', name='output')(x)
    
    return Model(image_input, out)

def main():
    create_train_val_csv(seed = 48, train_val_split = 0.2)
    
    model = create_model()
    model.summary()

    train_datagen = DataGenerator(TRAIN_CSV)
    validation_datagen = Validation(generator=DataGenerator(VALIDATION_CSV))
    model.compile(loss="mean_squared_error", optimizer="adam", metrics=['accuracy'])  
    
    checkpoint = ModelCheckpoint("./r3_Xception_checkpoints/model-1-{epoch:02d}-{val_iou:.2f}-.h5", monitor="val_iou", verbose=1, save_best_only=True,
                                 save_weights_only=True, mode="max", period=1)
        
        
    stop = EarlyStopping(monitor="val_iou", patience=PATIENCE, mode="max")
    reduce_lr = ReduceLROnPlateau(monitor="val_iou", factor=0.2, patience=10, min_lr=1e-7, verbose=1, mode="max")

    model.summary()
    model.fit_generator(generator=train_datagen,
                        epochs=EPOCHS,
                        callbacks=[validation_datagen, checkpoint, reduce_lr, stop],
                        shuffle=True,
                        verbose=1)
    get_predictions()

if __name__ == "__main__":
    main()