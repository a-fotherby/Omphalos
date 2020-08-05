"""Custom metrics for training Omphlos data sets."""
import tensorflow as tf

class SpeciesRmse(tf.keras.metrics.Metric):
    """Custom metric to measure the rmse of specific species being trained for in the model.
    
    Methods:
    update_state -- default method called by Keras to pass data to the metric when used with the compile() API. Computes the rmse for the target species.
    result -- method used by Keras compile() API to collect the calculated rmse.
    """
    
    def __init__(self, name, species_col, **kwargs):
        """Class constructor for the SpeciesRmse class.
        
        Arguments:
        name -- String identifying the metric. Must be unique, and must be human interpretable as this will identify the metric in wandb.
        species_col --  Int indentifying which column in the tensors y_true and y_pred contain the target species data.
        """
        super(SpeciesRmse, self).__init__(name=name, **kwargs)        
        self.species_col = species_col
        
    def update_state(self, y_true, y_pred):
        """Calulates the rmse in y_pred based on y_true.
        
        Is called by the Keras compile() API.
        """
        squared_diff = (tf.square(y_true[:,self.species_col] - y_pred[:,self.species_col]))
        rmse = tf.reduce_mean(squared_diff, axis=-1)
        
        self.rmse = rmse
    
    def result(self):
        """Returns the current calculated rmse.
        
        Is called by the Keras compile() API.
        """
        return self.rmse

def generate_metrics(*species_list, labels):
    """Returns a dictionary of metrics for analysing individual species perfomance in training.
    
    The DataFrame, labels_df *must* be the DataFrame that is passed to the model.
    """
    metrics = {}
    for species in species_list:
        species_col = labels.columns.get_loc(species)
        species_metric = SpeciesRmse(species, species_col)

        metrics.update({species: species_metric})
        
    return metrics