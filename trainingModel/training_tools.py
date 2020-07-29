import matplotlib.pyplot as plt
import tensorflow as tf
from tensorflow import keras
import numpy as np
import pandas as pd
import wandb
from wandb.keras import WandbCallback

def plot_history(history):
    """Plot a curve of loss vs. epoch."""
    plt.figure(figsize=(10, 8))
    plt.xlabel("Epoch")
    plt.ylabel("log(Mean Squared Error)")

    plt.plot(history.epoch, np.log10(history.history['loss']), label="Tranining Loss")
    plt.plot(history.epoch, np.log10(history.history['val_loss']), label="Validation Loss")
    plt.legend()
    #plt.ylim([mse.min()*0.95, mse.max() * 1.03])
    plt.show()  

    
def create_model(learning_rate, dropout):
    """Create and compile a simple linear regression model."""
    # Define the model geometry.
    model = tf.keras.models.Sequential([
    tf.keras.layers.Dense(128, activation='relu', kernel_regularizer=tf.keras.regularizers.l2(l=0.1)),
    tf.keras.layers.Dropout(dropout),
    tf.keras.layers.Dense(10)
    ])

    # Compile the model.
    model.compile(optimizer=tf.keras.optimizers.Adam(lr=learning_rate),
              loss=tf.keras.losses.MeanSquaredError(),
              metrics=['mse'])

    return model           


def train_model(model, features, labels, epochs, batch_size):
    """Feed a dataset into the model in order to train it."""

    # Split the dataset into features and label.
    history = model.fit(x=features, y=labels, batch_size=batch_size,
                      epochs=epochs, validation_split = 0.1, shuffle=True, verbose=0, callbacks=[WandbCallback()])

    # Get details that will be useful for plotting the loss curve.
    epochs = history.epoch
    hist = pd.DataFrame(history.history)
    rmse = hist["mse"]

    return history

def format_primary_species(data_set, condition, result_category, target_labels):
    """Takes a data set (a set of InputFile objects), a condition, and a target label and returns two dataframes; labels and attributes.
    
    The attribute array will be of dimension (# of InputFile objects x # of primary species).
    The labels array will be of dimension (# of InputFile objects x # target_labels)
    """
    # Put data into a dataframe for visualisation.
    attributes = pd.DataFrame()

    for i in data_set:
        append = pd.DataFrame.from_dict(data_set[i].condition_blocks[condition].primary_species)
        attributes = attributes.append(append, ignore_index = True)

    # Generate dataframe of requested labels.
    labels = pd.DataFrame()
    for label in target_labels:
        label_list = pd.DataFrame()
        for i in data_set:
            label_list = label_list.append(data_set[i].results.results_dict[result_category][label], ignore_index = True)
            
        label_list.columns = [label]
        labels[label] = label_list[label]

    
    return attributes, labels