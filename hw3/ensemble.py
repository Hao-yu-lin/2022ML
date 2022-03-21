import pandas as pd

df1 = pd.read_csv('model01.csv', index_col = 0)
df2 = pd.read_csv('model02.csv', index_col = 0)
df3 = pd.read_csv('model03.csv', index_col = 0)
df4 = pd.read_csv('model04.csv', index_col = 0)

df_combine = pd.concat([df1, df2, df3, df4],axis=1)
df_combine = df_combine.mode(axis=1).dropna(axis=1)

df_combine = df_combine.astype('int32')
df_combine.columns = ['Category']

df_combine.to_csv('Ensemble1.csv',index=True)