import tensorflow as tf
from tensorflow import keras
import seaborn as sns
import numpy as np
import matplotlib.pyplot as plt
import generate_inputs as gi
import file_methods as fm
import pandas as pd
import training_tools as tt

import yaml

import wandb
from wandb.keras import WandbCallback


print(tf.__version__)

# Unpickle the saved data set.
test_set = fm.unpickle('test.pickle')
train_set = fm.unpickle('train.pickle')
val_set = fm.unpickle('val.pickle')

# Put data into a dataframe for visualisation.
vis = pd.DataFrame()

for i in train_set:
    append = pd.DataFrame.from_dict(train_set[i].condition_blocks['Seawater'].primary_species)
    vis = vis.append(append, ignore_index = True)
    
# Create series from output data (pH).
pH = pd.DataFrame()

for i in train_set:
    pH = pH.append(train_set[i].results.results_dict['pH']['pH'], ignore_index = True)

pH.columns = ['pH']

# Normalise the pH to be on the scale 0-1ish
pH['pH'] = pH['pH'] / 14

x_train = vis.to_numpy()
y_train = pH.to_numpy()

print(np.shape(x_train))

# Put data into a dataframe for visualisation.
vis = pd.DataFrame()

for i in test_set:
    append = pd.DataFrame.from_dict(test_set[i].condition_blocks['Seawater'].primary_species)
    vis = vis.append(append, ignore_index = True)
    
# Create series from output data (pH).
pH = pd.DataFrame()

for i in test_set:
    pH = pH.append(test_set[i].results.results_dict['pH']['pH'], ignore_index = True)

pH.columns = ['pH']

# Normalise the pH to be on the scale 0-1ish
pH['pH'] = pH['pH'] / 14

x_test = vis.to_numpy()
y_test = pH.to_numpy()

def train():
    # wandb configuration
    #wandb.init(project="pH-box-model", config={'dropout': 0.2, 'learning_rate': 0.1, 'epochs': 100, 'batch_size': 50}, allow_val_change=True)
    wandb.init(project="pH-box-model", allow_val_change=True)
    # Hyperparameters defaults.
    #wandb.config.dropout = 0.2
    #wandb.config.learning_rate = 0.1
    #wandb.config.epochs = 100
    #wandb.config.batch_size = 50
    
    # Define the model geometry.
    model = tf.keras.models.Sequential([
    tf.keras.layers.Dense(128, activation='relu', kernel_regularizer=tf.keras.regularizers.l2(l=0.1)),
    tf.keras.layers.Dropout(wandb.config.dropout),
    tf.keras.layers.Dense(10)
    ])

    # Compile the model.
    model.compile(optimizer=tf.keras.optimizers.Adam(lr=wandb.config.learning_rate),
              loss=tf.keras.losses.MeanSquaredError(),
              metrics=['mse'])

    # Split the dataset into features and label.
    model.fit(x=x_train, y=y_train, batch_size=wandb.config.batch_size, epochs=wandb.config.epochs, validation_split = 0.1, shuffle=True, verbose=0, callbacks=[WandbCallback()])
train()
