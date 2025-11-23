import numpy as np

import wandb

from context import omphalos

# Import Omphalos modules.
from omphalos import generate_inputs as gi
from omphalos import file_methods as fm
from omphalos import omphalos_plotter as op
from omphalos import attributes as attr
from omphalos import labels as lbls
from omphalos import spatial_constructor

config_defaults = {'eta': 0.0001,
                    'l1': 0,
                    'l2': 1, 
                    'max_depth': 6
                    }

wandb.init(project='xgboost_rifle-sweep', config=config_defaults)

### Set random vars.
np.random.seed(0)

### Import and prep training/test data.
train_set = fm.unpickle('/Users/angus/Omphalos/fitting/data/old_rifle.pkl')

attributes_df = attr.boundary_condition(train_set, boundary='x_begin')
labels_df = lbls.secondary_precip(train_set)

x = attributes_df.loc[:, ['NH4+', 'SO4--','Ca++', 'Acetate', 'CO2(aq)']]
y = labels_df.sum(level=0)['FeS(am)'] + labels_df.sum(level=0)['FeS34(am)']

x = x.to_numpy()
y = y.to_numpy().reshape(-1,1)
y = y * 1e4

from sklearn.model_selection import train_test_split

x_train, x_test, y_train, y_test = train_test_split(x, y, test_size=0.2, random_state=69)


### Initialise booster model.
import xgboost as xgb


hyperparameter_defaults = dict(
    eta = 0.0001,
    l1 = 0,
    l2 = 1, 
    max_depth = 6
    )


config = wandb.config

dtrain = xgb.DMatrix(x_train, label=y_train)
dtest = xgb.DMatrix(x_test, label=y_test)

evallist = [(dtest, 'eval'), (dtrain, 'train')]
param = {'max_depth': config.max_depth, 'eta': config.eta, 'objective': 'reg:pseudohubererror', 'alpha': config.l1, 'lambda': config.l2}

results = {}

num_round = 1000
bst = xgb.train(param, dtrain, num_round, evallist, evals_result=results,early_stopping_rounds=500, verbose_eval=False, callbacks=[wandb.xgboost.wandb_callback()])

### Print RSME as output.

from sklearn.metrics import mean_squared_error
validation_lost = np.sqrt(mean_squared_error(y_test, ypred))

wandb.log({"val_loss": validation_loss})
