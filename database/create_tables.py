import os
import pandas as pd
from supabase_client import supabase


DATA_FOLDER="../Data"


def clean_table_name(filename):

    return (
        filename
        .replace(".csv","")
        .lower()
        .replace(" ","_")
        .replace("-","_")
    )


def get_sql_type(dtype):

    if "int" in str(dtype):
        return "BIGINT"

    if "float" in str(dtype):
        return "FLOAT"

    else:
        return "TEXT"


for file in os.listdir(DATA_FOLDER):

    if file.endswith(".csv"):

        path=os.path.join(DATA_FOLDER,file)

        table=clean_table_name(file)

        df=pd.read_csv(path)

        columns=[]

        for col in df.columns:

            columns.append(
                f'"{col.lower()}" {get_sql_type(df[col].dtype)}'
            )


        sql=f'''
        CREATE TABLE IF NOT EXISTS {table}(
            id BIGSERIAL PRIMARY KEY,
            {",".join(columns)}
        );
        '''


        print("\nCreating:",table)


        try:
            supabase.rpc(
                "exec_sql",
                {
                    "sql":sql
                }
            ).execute()

            print("DONE")

        except Exception as e:
            print(e)
