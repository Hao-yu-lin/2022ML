from matplotlib.pyplot import axis
import pandas as pd

mod1 = pd.read_csv('model01.csv', index_col = 0)
mod2 = pd.read_csv('model02.csv', index_col = 0)
mod3 = pd.read_csv('model03.csv', index_col = 0)

mod_combine = pd.concat([mod1, mod2, mod3], axis = 1)
mod_combine = mod_combine.mode(axis=1).dropna(axis=1)

mod_combine.columns = ['Category']

mod_combine.to_csv('Ensemble123.csv',index=True)