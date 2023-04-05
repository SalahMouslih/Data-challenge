# -*- coding: utf-8 -*-
"""code_serveur_final.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1A1lG2d7NYZazSIJZrjEaTYADjBRTjqJ2

# Import
"""

!pip install pyproj
!pip install pycraf
!pip install swifter
!pip install joblib
!pip  install -U  geopandas

# from google.colab import drive
# drive.mount('/content/drive')

import geopandas as gpd
import pandas as pd
import numpy as np
import sklearn as sk
import matplotlib.pyplot as plt
import swifter
import glob
import os
from sklearn.linear_model import LinearRegression
from numpy import mean
from datetime import datetime
from joblib import Parallel, delayed

import pycraf.geospatial as geo
import astropy.units as u
import math
from sklearn.neighbors import BallTree

"""# Import DVF
# ** LA SORTIE DOIT S'APPELER 'data'**
"""

def stat_sur_filtre(data):
  print(data.shape)
  print(data.groupby(['LIBEPCI']).size())
  return data.groupby(['LIBEPCI', 'type_local']).size()

def stat_before_after(data,clean_data):
    data.drop_duplicates(inplace=True)
    mask=(data.nature_mutation=="Vente")
    data=data[mask]
    mask=(data.type_local=="Appartement")|(data.type_local=="Maison")
    before_clean=data[mask]
    total_metropole_before=stat_sur_filtre(before_clean)
    total_metropole_after=stat_sur_filtre(clean_data)
    taux=(total_metropole_before-total_metropole_after)*100/total_metropole_before
    taux=taux.sort_values(ascending=False)
    result=pd.DataFrame(taux).reset_index().set_index('LIBEPCI')
    result.columns=['type_local','pourcentage (%)']
    for col in ["Appartement",'Maison']:
        result[result.type_local==col].sort_values(by='pourcentage (%)',ascending=False).plot.barh()
        plt.title(col)

data=pd.concat(map(pd.read_csv, glob.glob(os.path.join('', "/Challenge/GROUP4/TEDONZE/base_de_données/datadvf20*.csv"))))
# data=pd.concat(map(pd.read_csv, glob.glob(os.path.join('', "/content/drive/Shareddrives/BDC Meilleur Taux Grp 4/base de données/datadvf20*.csv"))))

data.shape

"""# Création des métropoles top 10 et Suppression des multiventes

## Fonction de création des métropoles
"""

# import the table which defines the metrpole (EPCI)
metropoles = pd.read_csv("/Challenge/GROUP4/TEDONZE/base_de_données/metropoles_communes.csv", delimiter = ';', header = 5)
# metropoles = pd.read_csv("/content/drive/Shareddrives/BDC Meilleur Taux Grp 4/base de données/metropoles_communes.csv", delimiter = ';', header = 5)

def zone_top(df, nb_top_zone):
  """ sélectionner les zones où il y a le plus de mutations """
  
  # correct the spelling of somme commune
  df.loc[df.nom_commune.str.startswith('Marseille '), 'nom_commune'] = 'Marseille'
  df.loc[df.nom_commune.str.startswith('Lyon '), 'nom_commune'] = 'Lyon'
  df.loc[df.nom_commune.str.startswith('Paris '), 'nom_commune'] = 'Paris'
  # merge dvf and metropole
  df = df.merge(metropoles, how = 'left',  left_on = 'nom_commune', right_on = 'LIBGEO')
  # pick the areas where we have the higher number of transaction
  most_frequent = df['LIBEPCI'].value_counts().head(nb_top_zone).index.to_list()
  df = df.loc[df['LIBEPCI'].isin(most_frequent)]

  return df

"""## Création et récupération des biens dans le top 10 des métropoles """

data_top = zone_top(data,10)
data_top.shape

"""# Fonction de clean, notamment des multiventes"""

def clean_type(clean_data,type_bien):
    mask = (clean_data.type_local == type_bien)
    clean_data = clean_data[mask]
    a = clean_data.groupby('index_group')['numero_disposition'].nunique()
    b = clean_data[clean_data.index_group.isin(a[a==1].index.to_list())].groupby('index_group').size()
    to_drop = b[b>1].index.to_list()
    clean_data = clean_data[~clean_data.index_group.isin(to_drop)]
    return clean_data

def clean_multivente(data):
    '''
    - drop the duplicates and only keep the 'Sale' transaction
    - drop all mutations with several disposition id (more complex mutations)
    - if we have the same mutation id several rows we filter by flat or house and make sure that we keep only one row for each type of good
    
        '''
    data.drop_duplicates(inplace=True)
    mask=(data.nature_mutation=="Vente")
    data=data[mask]
    data['index_group'] = data["id_mutation"].astype('string') + data['date_mutation'].astype('string')
    a = data.groupby('index_group')['numero_disposition'].nunique()
    to_drop = a[a>1].index.to_list()
    data = data[~data.index_group.isin(to_drop)]
    
    return pd.concat([clean_type(data,"Appartement"),clean_type(data,"Maison")])

"""# Nettoyage des multiventes"""
data_top = zone_top(data,10)

clean_data = clean_multivente(data_top)
clean_data.shape

stat_before_after(data_top,clean_data)

"""# Fonction closest GENERALE"""

def get_nearest(src_points, candidates, k_neighbors):
    """Find nearest neighbors for all source points from a set of candidate points"""

    # Create tree from the candidate points
    tree = BallTree(candidates, leaf_size = 15, metric = 'haversine')

    # Find closest points and distances
    distances, indices = tree.query(src_points, k = k_neighbors)

    return (indices, distances)

def nearest_neighbor(left_gdf, right_gdf, k_neighbors, return_dist=False):
    """
    For each point in left_gdf, find closest point in right GeoDataFrame and return them.
    NOTICE: Assumes that the input Points are in WGS84 projection (lat/lon).
    """
    left_geom_col = left_gdf.geometry.name
    right_geom_col = right_gdf.geometry.name

    # Ensure that index in right gdf is formed of sequential numbers
    right = right_gdf.copy().reset_index(drop=True)
    
    # Parse coordinates from points and insert them into a numpy array as RADIANS
    left_radians_x = left_gdf[left_geom_col].x.apply(lambda geom: geom * np.pi / 180)
    left_radians_y = left_gdf[left_geom_col].y.apply(lambda geom: geom * np.pi / 180)
    left_radians = np.c_[left_radians_x, left_radians_y]

    right_radians_x = right[right_geom_col].x.apply(lambda geom: geom * np.pi / 180)
    right_radians_y = right[right_geom_col].y.apply(lambda geom: geom * np.pi / 180)
    right_radians = np.c_[right_radians_x, right_radians_y]

    closest, dist = get_nearest(src_points = left_radians, candidates = right_radians, k_neighbors = k_neighbors)

    return closest


def my_choose_closest(dvf, table_info, k_neighbors, metric_interest, name_new_metric, reg=False):
    """ 
    get our metric of interest in the original dataframe
    calculated from the table_info with the function applied to the k_neighbors closest neighbors in the table_info dataframe
    
    """
    dvf[name_new_metric] = np.nan
    closest = nearest_neighbor(dvf, table_info.reset_index(drop=True), k_neighbors, return_dist = True)
    dvf['indices'] = list(closest)
    

    if reg:
        
        def apply_linear_regression(row, metric_interest):
            indices = row['indices']
            X = table_info.loc[indices, ['surface_reelle_bati', 'nombre_pieces_principales']].values
            prix = table_info.loc[indices, metric_interest].values

            lr = LinearRegression()
            lr.fit(X, prix)
    
            return lr.intercept_
        dvf[name_new_metric] = dvf.swifter.apply(
            lambda row: apply_linear_regression(row, metric_interest),
            axis=1
        )
    else:
        dvf[name_new_metric] = dvf['indices'].apply(lambda x: table_info[metric_interest].iloc[x].mean())

    return dvf

"""# Préparation DVF

## Fonctions d'actualisation temporelle des prix
"""

path_valeur_indice="/Challenge/GROUP4/TEDONZE/valeurs_trimestrielles.csv"
path_zonage_immo="/Challenge/GROUP4/TEDONZE/Zonage_abc_communes_2022.xlsx"

"""On définit les différentes fonctions utilisées ensuite"""

def create_columns(data):
    liste_var=data.columns
    for i in liste_var:
        if 'Appartement' in i :
            new_var= i.replace('Appartement', 'Maison' )
            if new_var not in liste_var:
                data[new_var]=data[i]*data['coeff_appart_a_maison']
        if 'Maison' in i :
            new_var= i.replace('Maison', 'Appartement' )
            if new_var not in liste_var:
                data[new_var]=data[i]*data['coeff_maison_a_appart']
    return data

def commune (x):
    commune=str(x)
    commune_new=commune
    if len(commune)==4:
        commune_new='0'+commune
    return commune_new

def fill_zone(data):
    x=data['Zone ABC']
    nom=data['nom_commune']
    if nom in liste_Marseille:
        zone='Marseille'
    elif nom in liste_lyon:
        zone='Lyon'
    elif nom in liste_paris:
        zone='Paris'
    elif nom in ['Lille']:
        zone='Lille'   
    elif pd.isna(x):
        if nom not in liste_complete:
            zone= 'C'
    else:
        zone=x
    return zone


def get_trimestre(data):
    date=data['date_vente']
    mois=int(date.month)
    year=date.year
    trimestre=''
    if mois<4:
        trimestre='T1'
    elif (mois>=4) and (mois<7):
        trimestre='T2'
    elif (mois>=7) and (mois<10):
        trimestre='T3' 
    else:
        trimestre='T4' 
    trim_vente=str(year)+'-'+str(trimestre)
    return trim_vente

    
liste_grande_ville=['Indice des prix des logements anciens - Agglomération de Marseille - Appartements - Base 100 en moyenne annuelle 2015 - Série CVS',
                   'Indice des prix des logements anciens - Agglomération de Lille - Maisons - Base 100 en moyenne annuelle 2015 - Série CVS',
                   'Indice des prix des logements anciens - Agglomération de Lyon - Appartements - Base 100 en moyenne annuelle 2015 - Série CVS',
                   'Indice des prix des logements anciens - Paris - Appartements - Base 100 en moyenne annuelle 2015 - Série CVS',
                   'Indice des prix des logements anciens - France métropolitaine - Appartements - Base 100 en moyenne annuelle 2015 - série CVS',
                   'Indice des prix des logements anciens - France métropolitaine - Maisons - Base 100 en moyenne annuelle 2015 - Série CVS',
                   "Indice des prix des logements anciens - Zone A du Zonage A, B, C - Base 100 en moyenne annuelle 2015 - Série CVS",
                   "Indice des prix des logements anciens - Zone A bis du Zonage A, B, C - Base 100 en moyenne annuelle 2015 - Série CVS",
                   "Indice des prix des logements anciens - Zone B1 du Zonage A, B, C - Base 100 en moyenne annuelle 2015 - Série CVS",
                   "Indice des prix des logements anciens - Zone B2 du Zonage A, B, C - Base 100 en moyenne annuelle 2015 - Série CVS",
                   "Indice des prix des logements anciens - Zone C du Zonage A, B, C - Base 100 en moyenne annuelle 2015 - Série CVS"]

liste_Marseille=['Marseille 2e Arrondissement',
       'Marseille 3e Arrondissement', 'Marseille 1er Arrondissement',
       'Marseille 15e Arrondissement', 'Marseille 14e Arrondissement',
       'Marseille 4e Arrondissement', 'Marseille 16e Arrondissement',
       'Marseille 7e Arrondissement', 'Marseille 10e Arrondissement',
       'Marseille 6e Arrondissement', 'Marseille 5e Arrondissement',
       'Marseille 8e Arrondissement', 'Marseille 9e Arrondissement',
       'Marseille 12e Arrondissement', 'Marseille 13e Arrondissement',
       'Marseille 11e Arrondissement']
                 
liste_lyon=['Lyon 9e Arrondissement',
       'Lyon 1er Arrondissement', 'Lyon 2e Arrondissement',
       'Lyon 5e Arrondissement', 'Lyon 4e Arrondissement',
       'Lyon 8e Arrondissement', 'Lyon 3e Arrondissement',
       'Lyon 7e Arrondissement', 'Lyon 6e Arrondissement']
                 
liste_paris=['Paris 8e Arrondissement',
       'Paris 3e Arrondissement', 'Paris 1er Arrondissement',
       'Paris 18e Arrondissement', 'Paris 7e Arrondissement',
       'Paris 5e Arrondissement', 'Paris 6e Arrondissement',
       'Paris 11e Arrondissement', 'Paris 13e Arrondissement',
       'Paris 10e Arrondissement', 'Paris 9e Arrondissement',
       'Paris 12e Arrondissement', 'Paris 14e Arrondissement',
       'Paris 15e Arrondissement', 'Paris 16e Arrondissement',
       'Paris 17e Arrondissement', 'Paris 20e Arrondissement',
       'Paris 19e Arrondissement', 'Paris 2e Arrondissement',
       'Paris 4e Arrondissement']

liste_complete=liste_paris+liste_lyon+liste_Marseille

"""On définit la fonction d'actulisation des prix, qui rajoute une colomne coefficient_actualisation"""

def get_coeff_actu(data,base_indice_grand,trimestre_actu):
        zone=data['vrai_zone']
        trimestre=data['trimestre_vente']
        type_bien=data['type_local']
        ligne=''    
        if zone=='Paris':
            if type_bien=='Appartement':
                ligne='Indice des prix des logements anciens - Paris - Appartements - Base 100 en moyenne annuelle 2015 - Série CVS'
            else:
                ligne='Indice des prix des logements anciens - Paris - Maisons - Base 100 en moyenne annuelle 2015 - Série CVS'

        elif zone=='Marseille':
            if type_bien=='Appartement':
                ligne='Indice des prix des logements anciens - Agglomération de Marseille - Appartements - Base 100 en moyenne annuelle 2015 - Série CVS'
            else:
                ligne='Indice des prix des logements anciens - Agglomération de Marseille - Maisons - Base 100 en moyenne annuelle 2015 - Série CVS'

        elif zone=='Lyon':
            if type_bien=='Appartement':
                ligne='Indice des prix des logements anciens - Agglomération de Lyon - Appartements - Base 100 en moyenne annuelle 2015 - Série CVS'
            else:
                ligne='Indice des prix des logements anciens - Agglomération de Lyon - Maisons - Base 100 en moyenne annuelle 2015 - Série CVS'

        elif zone=='Lille':
            if type_bien=='Appartement':
                ligne='Indice des prix des logements anciens - Agglomération de Lille - Appartements - Base 100 en moyenne annuelle 2015 - Série CVS'
            else:
                ligne='Indice des prix des logements anciens - Agglomération de Lille - Maisons - Base 100 en moyenne annuelle 2015 - Série CVS'

        elif zone=='A':
            ligne="Indice des prix des logements anciens - Zone A du Zonage A, B, C - Base 100 en moyenne annuelle 2015 - Série CVS"
        elif zone=='Abis':
            ligne="Indice des prix des logements anciens - Zone A bis du Zonage A, B, C - Base 100 en moyenne annuelle 2015 - Série CVS"
        elif zone=='B1':
            ligne="Indice des prix des logements anciens - Zone B1 du Zonage A, B, C - Base 100 en moyenne annuelle 2015 - Série CVS"
        elif zone=='B2':
            ligne="Indice des prix des logements anciens - Zone B2 du Zonage A, B, C - Base 100 en moyenne annuelle 2015 - Série CVS"
        elif zone=='C':
            ligne="Indice des prix des logements anciens - Zone C du Zonage A, B, C - Base 100 en moyenne annuelle 2015 - Série CVS"
        
        # we only keep the row we are interested in
        données=base_indice_grand[base_indice_grand['Libellé'].isin([ligne])]
 
        # we get the index
        # indice_ancien=float(données[trimestre])
        # indice_actu=float(données['2022-T3'])
        indice_ancien=données[trimestre].apply(lambda x: float(x))
        indice_actu=données[trimestre_actu].apply(lambda x: float(x))

        coeff=float(((indice_actu-indice_ancien)/indice_ancien)+1)

        return coeff

def fonction_final_prix(data,trimestre_actu,actulisation=True):
    # we process the real estate indices table
    base_indice=pd.read_csv(path_valeur_indice,sep=';')
    base_indice=base_indice[['Libellé','2016-T1', '2016-T2', '2016-T3', '2016-T4', '2017-T1', '2017-T2',
       '2017-T3', '2017-T4', '2018-T1', '2018-T2', '2018-T3', '2018-T4',
       '2019-T1', '2019-T2', '2019-T3', '2019-T4', '2020-T1', '2020-T2',
       '2020-T3', '2020-T4', '2021-T1', '2021-T2', '2021-T3', '2021-T4',
       '2022-T1', '2022-T2', '2022-T3']]

    base_indice_grand=base_indice[base_indice['Libellé'].isin(liste_grande_ville)]
    base_indice_grand.set_index('Libellé',inplace=True)
    base_indice_grand=base_indice_grand.transpose()

    base_indice_grand.replace('(s)', np.nan,inplace=True)
    base_indice_grand.fillna( method='ffill',inplace=True)
    base_indice_grand=base_indice_grand.astype('float')

    # create the coefficient variables
    base_indice_grand['coeff_maison_a_appart']=base_indice_grand['Indice des prix des logements anciens - France métropolitaine - Appartements - Base 100 en moyenne annuelle 2015 - série CVS']/base_indice_grand['Indice des prix des logements anciens - France métropolitaine - Maisons - Base 100 en moyenne annuelle 2015 - Série CVS']
    base_indice_grand['coeff_appart_a_maison']=base_indice_grand['Indice des prix des logements anciens - France métropolitaine - Maisons - Base 100 en moyenne annuelle 2015 - Série CVS']/base_indice_grand['Indice des prix des logements anciens - France métropolitaine - Appartements - Base 100 en moyenne annuelle 2015 - série CVS']

    base_indice_grand=create_columns(base_indice_grand)

    liste_drop=['coeff_maison_a_appart', 'coeff_appart_a_maison','Indice des prix des logements anciens - France métropolitaine - Maisons - Base 100 en moyenne annuelle 2015 - série CVS',
       'Indice des prix des logements anciens - France métropolitaine - Appartements - Base 100 en moyenne annuelle 2015 - Série CVS']
    base_indice_grand.drop(columns=liste_drop,inplace=True)
    base_indice_grand=base_indice_grand.transpose()
    base_indice_grand.reset_index(inplace=True)

    # import of the real estate areas table
    zone=pd.read_excel(path_zonage_immo)
    zone.rename({'Nom Commune': 'nom_commune'}, axis='columns',inplace=True)

    # we join  dvf and the area table, and then replace the NA
    data['Code Commune']=data['code_commune'].apply(lambda x: commune(x)).astype("str")
    data_join = pd.merge(data, zone,how="left", on='Code Commune')
    
    data_join['vrai_zone']=data_join.apply(lambda x: fill_zone(x),axis=1)
    
    # we get the sale trimesters
    data_join['date_vente'] = data_join['date_mutation'].apply(lambda x: datetime.strptime(x, '%Y-%m-%d'))
    data_join['trimestre_vente']=data_join.apply(lambda x: get_trimestre(x),axis=1)
    
    
    #data_join=data_join[data_join['vrai_zone'].isin(['A','Abis','Paris','Lille','Lyon','Marseille'])]
    #data_join=data_join[data_join['vrai_zone'].isin(['Paris'])]
    if actulisation:

        def your_func(row):

          return get_coeff_actu(row,base_indice_grand,trimestre_actu)

        # we compute the actualisation coefficient
        data_join['coeff_actu']=data_join.swifter.apply(lambda x: your_func(x),axis=1)
        liste_drop_zone=['Zone ABC','vrai_zone','date_vente']
        data_join.drop(columns=liste_drop_zone,inplace=True)


        # we create the target variable : 'prix_actualise'
        data_join['prix_actualise'] = data_join['valeur_fonciere'] * data_join['coeff_actu']

        # we create the  target variable : 'prix_m2'
        data_join['prix_m2_actualise'] = data_join['prix_actualise'] / data_join['surface_reelle_bati']
        data_join['prix_m2'] = data_join['valeur_fonciere'] / data_join['surface_reelle_bati']
    
    return data_join

"""## Fonctions de filtrage des données 

"""

def select_bien(df):
  """ fonction pour faire les premières modification sur la base dvf """
  
  # we only keep the 'Vente' transactions
  df = df[df['nature_mutation'] == 'Vente']
  # we only keep the 'Maison' and 'Appartement' goods
  df = df.loc[df['type_local'].isin(['Maison', 'Appartement'])]
  # we only keep the goods for which we have the localisation because most of our analysis relies on it
  df = df[(df['latitude'].notna()) & (df['longitude'].notna())]
  return df

def filtre_dur(df, bati, piece, local, metropole_name=None):
    """Filtre les valeurs abbérantes sur 3 variables pour une métropole donnée."""
    
    if metropole_name:
        df_metropole = df[(df['type_local'] == local) & (df['LIBEPCI'] == metropole_name)]
        df_other_metropoles = df[(df['LIBEPCI'] != metropole_name) | ((df['LIBEPCI'] == metropole_name) & (df['type_local'] != local))]
    else:
        df_metropole = df[df['type_local'] == local]
        df_other_metropoles = df[df['type_local'] != local]
    
    df_metropole = df_metropole[(df_metropole['surface_reelle_bati'] <= bati) &
                                (df_metropole['nombre_pieces_principales'] <= piece)]
    
    # merge filtered data for the given local in metropole with data for other metropoles
    df_filtered = pd.concat([df_metropole, df_other_metropoles])
    
    return df_filtered

def filtre_prix(df,metric_prix,quantile_nv = 0.99):
  """ 
  function to  filter the absurd prix/m2
  we compute the quantile 0.99,for each city (not EPCI, city being more precise) and each type of good (Maison, Appartement)
  then we filter the goods based on this quantile 
  ++++++ Be careful to use the actualised price ++++++
  """

  df = df[(df[metric_prix] >= 1000) & (df[metric_prix] <= 20000)]


  quantile_per_city_type = (
        df.groupby(['nom_commune', 'type_local'])
          .agg({metric_prix: lambda x: np.quantile(x, quantile_nv)})
          .rename(columns={metric_prix: 'quantile_prix'})
          .reset_index()
    )

  df = df.merge(quantile_per_city_type, on=['nom_commune', 'type_local'], how='left')

  df = df[df[metric_prix] < df['quantile_prix']]

  return df

"""### Stats"""

# def get_quantile_df(grouped_data, column_name, quantile):

#     quantiles = {}
#     for group_name, group_data in grouped_data:
#         quantiles[group_name] = group_data[column_name].quantile(quantile)

#     df = pd.DataFrame.from_dict(quantiles, orient='index', columns=[f'{column_name} {quantile*100:.0f}th p'])

#     return df
# # group data by local and metropole:
# grouped = dvf.groupby(['type_local', 'LIBEPCI'])
# import math

# column_names = ['surface_reelle_bati', 'nombre_pieces_principales']
# quantiles_df = pd.DataFrame()

# for column_name in column_names:
#     column_df = get_quantile_df(grouped, column_name, 0.99)
#     quantiles_df = pd.concat([quantiles_df, column_df], axis=1)

# quantiles_df = quantiles_df.applymap(lambda x: math.ceil(x))
# quantiles_df

"""## Première série de filtre, sur les caractéristiques non-prix, tant qu'ils n'ont pas été actualisés"""

dvf = select_bien(clean_data)
stat_sur_filtre(dvf)

"""After analysis (see part of the code with the filter functions), we decided to set the following filter criteria: for houses, a maximum built-up area of 360 m² and a maximum number of main rooms of 10; for flats, a maximum built-up area of 200 m² and a maximum number of main rooms of 6"""
dvf = select_bien(clean_data)

dvf = filtre_dur(dvf, 360, 10, 'Maison')
dvf = filtre_dur(dvf, 200, 6, 'Appartement')
stat_sur_filtre(dvf)

"""## On actualise les prix"""

test = fonction_final_prix(dvf,trimestre_actu='2022-T2',actulisation=False)

# we observe year by year to choose the split date 
find_pourcentage=(test['trimestre_vente'].value_counts(normalize=True)).sort_index().cumsum()
find_pourcentage

find_pourcentage[find_pourcentage>0.8]

# test[test['trimestre_vente'].isin(['2022-T1','2022-T2','2022-T3','2022-T4'])].groupby(['type_local', 'LIBEPCI']).sum() / test.groupby(['type_local', 'LIBEPCI']).sum()

dvf = fonction_final_prix(dvf,trimestre_actu='2021-T2')
stat_sur_filtre(dvf)

dvf_geo = dvf
test_trimestre=['2021-T3','2021-T4','2022-T1','2022-T2']

"""## On poursuit les filtres, cette fois sur les prix, après les avoir actualisés"""

dvf_train=dvf_geo[~dvf_geo['trimestre_vente'].isin(test_trimestre)]
dvf_test=dvf_geo[dvf_geo['trimestre_vente'].isin(test_trimestre)]
dvf_train = filtre_prix(dvf_train,'prix_m2_actualise', 0.99)
dvf_test = filtre_prix(dvf_test,'prix_m2', 0.99)
dvf_geo = pd.concat([dvf_train, dvf_test])
stat_sur_filtre(dvf_geo)

# convert to geopandas
def convert_gpd(df):
  return gpd.GeoDataFrame(
    df, geometry = gpd.points_from_xy(df.longitude, df.latitude))

dvf_geo = convert_gpd(dvf_geo)

stat_sur_filtre(dvf_geo)

"""## On intègre le prix moyen des 10 biens les plus proches"""

# we create the variable "prix moyen au m2 des 10 biens les plus proches"
dvf_geo = my_choose_closest(dvf = dvf_geo, table_info = dvf_geo[~dvf_geo['trimestre_vente'].isin(test_trimestre)],
               k_neighbors = 10,
               metric_interest = 'prix_m2_actualise',
               name_new_metric = 'prix_m2_zone')

dvf_geo = dvf_geo.reset_index(drop=True)

# # on crée la variable "intercept moyen des régressions de chacun des 10 biens les plus proches sur leurs caractéristiques (surface, nombre de pièces)"
# table_info=dvf_geo[~dvf_geo['trimestre_vente'].isin(test_trimestre)]
# table_info=table_info.reset_index()                                                  
# dvf_geo = my_choose_closest(dvf = dvf_geo, table_info=table_info ,
#                k_neighbors = 10,
#                metric_interest = 'prix_m2_actualise',
#                name_new_metric = 'intercept', reg=True)
# stat_sur_filtre(dvf_geo)

"""# Etablissements scolaires

## Fonctions pour préparer les données des lycées et collèges
"""

def prep_lyc(data, geo_etab):

  '''
  Choose the lycées généraux (more likely to influence the prices than other schools)
  Get the taux de mention for each lycée
  Convert to geopandas and then merge with dvf
  '''

  lyc = data[data['Annee'] == 2020]
  lyc_gen = lyc[['Etablissement', 'UAI', 'Code commune',
                'Presents - L', 'Presents - ES', 'Presents - S',
                'Taux de mentions - L', 
                'Taux de mentions - ES',
                'Taux de mentions - S']]
  lyc_gen = lyc_gen[(lyc_gen['Presents - L']>0) |
    (lyc_gen['Presents - ES']>0)|
    (lyc_gen['Presents - S']>0)]
  lyc_gen = lyc_gen.fillna(0)
  lyc_gen['taux_mention'] = (lyc_gen['Presents - L'] * lyc_gen['Taux de mentions - L'] + lyc_gen['Presents - ES'] * lyc_gen['Taux de mentions - ES'] + lyc_gen['Presents - S'] * lyc_gen['Taux de mentions - S']) / (lyc_gen['Presents - S'] + lyc_gen['Presents - L'] + lyc_gen['Presents - ES'])
  lyc_gen = lyc_gen.merge(geo_etab, how = 'left', left_on = 'UAI', right_on = 'numero_uai')
  lyc_gen = lyc_gen[['Etablissement', 'UAI', 'Code commune', 'code_departement',
          'Taux de mentions - L', 'Taux de mentions - ES', 'Taux de mentions - S', 'taux_mention',
          'latitude', 'longitude']]
  lyc_gen.rename(columns = {'Taux de mentions - L':'taux_mention_L', 'Taux de mentions - ES':'taux_mention_ES', 'Taux de mentions - S':'taux_mention_S'})
  lyc_gen_geo = gpd.GeoDataFrame(
      lyc_gen, geometry = gpd.points_from_xy(lyc_gen.longitude, lyc_gen.latitude))
  lyc_gen_geo = lyc_gen_geo[(lyc_gen_geo['latitude'].notna()) & (lyc_gen_geo['longitude'].notna())]

  return lyc_gen_geo

def prep_brevet(data, geo_etab):

  '''
  Get the taux de mention for each collège
  Convert to geopandas and then merge with dvf
  '''

  brevet = data[data['session'] == 2021]
  brevet_geo = brevet.merge(geo_etab, how = 'left', left_on = 'numero_d_etablissement', right_on = 'numero_uai')
  brevet_geo = brevet_geo[['numero_uai', 'code_commune',
          'nombre_total_d_admis', 'nombre_d_admis_mention_tb','taux_de_reussite',
          'latitude', 'longitude']]
  brevet_geo['taux_mention'] = brevet_geo['nombre_d_admis_mention_tb'] / brevet_geo['nombre_total_d_admis']

  brevet_geo = gpd.GeoDataFrame(
      brevet_geo, geometry = gpd.points_from_xy(brevet_geo.longitude, brevet_geo.latitude))
  brevet_geo = brevet_geo[(brevet_geo['latitude'].notna()) & (brevet_geo['longitude'].notna())]

  return brevet_geo

"""## Intégration des données sur les établissements scolaire dans dvf"""

# geo_etab : geographical coordinates of schools
geo_etab = pd.read_csv('/Challenge/GROUP4/TEDONZE/base_de_données/geo_brevet.csv', delimiter = ';')
# brevet : results at brevet for each collège
brevet = pd.read_csv('/Challenge/GROUP4/TEDONZE/base_de_données/resultats_brevet.csv', delimiter = ';')
# lyc : results at baccalauréat for each lycée
lyc =  pd.read_csv("/Challenge/GROUP4/TEDONZE/base_de_données/resultats_lycées.csv", sep = ';')

# Get the taux de mention for each lycée + geographical coordinates of schools
lyc_gen_geo = prep_lyc(lyc, geo_etab)
brevet_geo = prep_brevet(brevet, geo_etab)

# We get for each good the average taux de mention of the 3 closest lycées
dvf_geo = my_choose_closest(dvf = dvf_geo,
               table_info = lyc_gen_geo,
               k_neighbors = 3,
               metric_interest = 'taux_mention',
               name_new_metric = 'moyenne')
stat_sur_filtre(dvf_geo)

# Get the taux de mention for each collège + geographical coordinates of schools
brevet_geo = prep_brevet(brevet, geo_etab)

# We get for each good the average taux de mention of the 3 closest collèges
dvf_geo = my_choose_closest(dvf = dvf_geo,
                  table_info = brevet_geo,
                  k_neighbors = 3,
                  metric_interest = 'taux_mention',
                  name_new_metric = 'moyenne_brevet')
stat_sur_filtre(dvf_geo)

"""# IRIS

## Préparation des bases IRIS
"""

iris_value = pd.read_csv('/Challenge/GROUP4/TEDONZE/base_de_données/IRIS_donnees.csv', delimiter = ';')
iris_shape = gpd.read_file('/Challenge/GROUP4/TEDONZE/base_de_données/IRIS_contours.shp')

iris_shape.drop_duplicates(subset=['DCOMIRIS'], keep = 'first', inplace = True)
iris_value.drop_duplicates(subset=['IRIS'], keep = 'first', inplace = True)

def iris_prep(iris_value, iris_shape, value_on, shape_on):

  iris_shape.drop_duplicates(subset=['DCOMIRIS'], keep = 'first', inplace = True)
  iris_value.drop_duplicates(subset=['IRIS'], keep = 'first', inplace = True)
  iris_value[value_on] = iris_value[value_on].astype(str).str.rjust(9, '0')

  # merge iris_shape and iris_value to get the polygones and the IRIS values in the same table
  iris = iris_shape.merge(iris_value, how = 'left', right_on = value_on, left_on = shape_on)
  iris.drop_duplicates(subset=['DCOMIRIS'], keep = 'first', inplace = True)

  return iris

iris = iris_prep(iris_value, iris_shape, 'IRIS', 'DCOMIRIS')

"""## Merge IRIS avec dvf"""

dvf_geo = dvf_geo.sjoin(iris, how = 'left', predicate = 'within')

stat_sur_filtre(dvf_geo)

liste_new = ['Taux_pauvreté_seuil_60', 'Q1', 'Mediane', 'Q3', 'Ecart_inter_Q_rapporte_a_la_mediane', 'D1', 'D2', 'D3', 'D4',
                                             'D5', 'D6', 'D7', 'D8', 'D9', 'Rapport_interdécile_D9/D1', 'S80/S20', 'Gini', 'Part_revenus_activite',
                                             'Part_salaire', 'Part_revenus_chomage', 'Part_revenus_non_salariées', 'Part_retraites', 'Part_revenus_patrimoine',
                                             'Part_prestations_sociales', 'Part_prestations_familiales', 'Part_minima_sociaux', 'Part_prestations_logement',
                                             'Part_impôts']
             

variable=['DISP_TP6019', 'DISP_Q119',
       'DISP_MED19', 'DISP_Q319', 'DISP_EQ19', 'DISP_D119', 'DISP_D219',
       'DISP_D319', 'DISP_D419', 'DISP_D619', 'DISP_D719', 'DISP_D819',
       'DISP_D919', 'DISP_RD19', 'DISP_S80S2019', 'DISP_GI19', 'DISP_PACT19',
       'DISP_PTSA19', 'DISP_PCHO19', 'DISP_PBEN19', 'DISP_PPEN19',
       'DISP_PPAT19', 'DISP_PPSOC19', 'DISP_PPFAM19', 'DISP_PPMINI19',
       'DISP_PPLOGT19', 'DISP_PIMPOT19', 'DISP_NOTE19']


def fonc(params):
       var=params[0]
       new_var=params[1]
       print(new_var)
       return my_choose_closest(dvf = dvf_geo, table_info = dvf_geo[dvf_geo[var].notnull()],
                k_neighbors = 1,
                metric_interest = var,
                name_new_metric = new_var)[new_var]
       
       #dvf_geo.drop(columns=var,inplace=True)





results = Parallel(n_jobs=-1, verbose=1)\
    (delayed(fonc)(i) for i in zip(variable,liste_new))

temp=pd.concat(results,axis=1)
dvf_geo.drop(variable,inplace=True,axis=1)
dvf_geo=pd.concat([dvf_geo,temp],axis=1)

dvf_geo



stat_sur_filtre(dvf_geo)

"""# EQUIPEMENTS

## Fonction de préparation des équipements
"""

liste_equipements_finale = [['A203'],['A206'],['B101','B102','B103','B201','B202','B203','B204','B205','B206'],['C101','C102','C104','C105'],
                     ['C201','C301','C302','C303','C304','C305'],['D201'],['E107','E108','E109'],['F303'],['F307'],['F313']]
                     
#BANQUE CAISSE D EPARGNE

#BUREAU DE POSTE 

#HYPERMARCHE, SUPERMARCHE, GRANDE SURFACE DE BRICOLAGE, SUPERETTE EPICERIE, BOULANGERIE, BOUCHERIE CHARCUTERIE, PRODUITS SURGELES, POISSONNERIE

#ECOLE MATERNELLE, ECOLE MATERNELLE DE REGROUPEMENT PEDAGOGIQUE, ECOLE ELEMENTAIRE, ECOLE ELEMENTAIRE DE REGROUPEMENT PEDAGOGIQUE 

#COLLEGE, LYCEE D ENSEIGNEMENT GENERAL ET OU TECHNOLOGIQUE, LYCEE D ENSEIGNEMENT PROFESSIONNEL, LYCEE D ENSEIGNEMENT TECHNIQUE ET OU PROFESSIONNEL AGRICOLE, SGT SECTION D ENSEIGNEMENT GENERAL ET TECHNOLOGIQUE, SEP SECTION D ENSEIGNEMENT PROFESSIONNEL

#MEDECIN GENERALISTE 

#GARE DE VOYAGEURS D INTERET NATIONAL, GARE DE VOYAGEURS D INTERET REGIONAL, GARE DE VOYAGEURS D INTERET LOCAL

#CINEMA

#BIBLIOTHEQUE

#ESPACE REMARQUABLE ET PATRIMOINE

def equipements_prep(df_equi, liste_equipements = liste_equipements_finale):
  """
  Agréger le nombre d'equipements pour les catégories choisies au niveau des IRIS
  """
  df_equi = df_equi[df_equi['DCIRIS'].isin(liste_iris)]
  equipements = []

  for liste_equipement in liste_equipements:

    df_equip = df_equi[df_equi['TYPEQU'].isin(liste_equipement)]
    df_equip = df_equip.groupby('DCIRIS')['TYPEQU'].value_counts().to_frame()
    df_equip = df_equip.groupby('DCIRIS').sum()
    df_equip = df_equip.rename(columns={"TYPEQU": liste_equipement[0]})
    equipements.append(df_equip)

  equipements = pd.concat(equipements).fillna(0)
  equipements['DCIRIS'] = equipements.index
  equipements = equipements.reset_index(drop=True)

  return equipements

stat_sur_filtre(dvf_geo)

"""## Intégration des équipements dans dvf"""

dvf_geo.columns

liste_iris = dvf_geo['DCOMIRIS'].unique()

liste_iris

equi = pd.read_csv('/Challenge/GROUP4/TEDONZE/base_de_données/bpe21_ensemble_xy.csv', delimiter = ';')

equipements = equipements_prep(equi, liste_equipements_finale)

equipements.drop_duplicates(inplace=True)
equipements=equipements.groupby(["DCIRIS"],as_index=False).sum()

dvf_geo = dvf_geo.merge(equipements, how = 'left', left_on = 'DCOMIRIS', right_on = 'DCIRIS')
stat_sur_filtre(dvf_geo)

liste_new = ['Banques', 'Bureaux_de_Poste', 'Commerces', 'Ecoles','Collèges_Lycées', 'Medecins','Gares', 'Cinema',
             'Bibliotheques', 'Espaces_remarquables_et_patrimoine']            

variable=['A203', 'A206', 'B101', 'C101', 'C201', 'D201', 'E107', 'F303', 'F307', 'F313']

results = Parallel(n_jobs=-1, verbose=1)\
    (delayed(fonc)(i) for i in zip(variable,liste_new))

temp=pd.concat(results,axis=1)
dvf_geo.drop(variable,inplace=True,axis=1)
dvf_geo=pd.concat([dvf_geo,temp],axis=1)

liste_var_garder=['id_mutation', 'date_mutation', 'numero_disposition', 'valeur_fonciere',
       'adresse_numero', 'adresse_nom_voie', 'adresse_code_voie',
       'code_commune', 'nom_commune', 'code_departement', 'LIBEPCI',
       'id_parcelle', 'nombre_lots', 'lot1_numero', 'lot1_surface_carrez',
       'lot2_numero', 'lot2_surface_carrez', 'lot3_numero',
       'lot3_surface_carrez', 'lot4_numero', 'lot4_surface_carrez',
       'lot5_numero', 'lot5_surface_carrez', 'type_local',
       'surface_reelle_bati', 'nombre_pieces_principales', 'surface_terrain',
       'longitude', 'latitude', 'geometry', 'quantile_prix', 'coeff_actu','prix_actualise','prix_m2_actualise','prix_m2','trimestre_vente','prix_m2_zone',
        'moyenne','moyenne_brevet','DCOMIRIS','indices', 'Banques', 'Bureaux_de_Poste', 'Commerces', 'Ecoles','Collèges_Lycées', 'Medecins',
       'Gares', 'Cinema', 'Bibliotheques', 'Espaces_remarquables_et_patrimoine', 'DCIRIS',
       'Taux_pauvreté_seuil_60', 'Q1', 'Mediane', 'Q3', 'Ecart_inter_Q_rapporte_a_la_mediane', 'D1', 'D2', 'D3', 'D4',
       'D5', 'D6', 'D7', 'D8', 'D9', 'Rapport_interdécile_D9/D1', 'S80/S20', 'Gini', 'Part_revenus_activite',
       'Part_salaire', 'Part_revenus_chomage', 'Part_revenus_non_salariées', 'Part_retraites', 'Part_revenus_patrimoine',
       'Part_prestations_sociales', 'Part_prestations_familiales', 'Part_minima_sociaux', 'Part_prestations_logement','Part_impôts']

dvf_geo_final=dvf_geo[liste_var_garder]

#execute this when done
pd.DataFrame(dvf_geo_final).to_csv('Final.csv', index=False)



