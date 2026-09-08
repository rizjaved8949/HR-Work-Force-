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
    )


for file in os.listdir(DATA_FOLDER):

    if file.endswith(".csv"):

        path=os.path.join(
            DATA_FOLDER,
            file
        )

        table=clean_table_name(file)


        print(
            "Uploading:",
            table
        )


        df=pd.read_csv(path)


        data=df.fillna("").to_dict(
            orient="records"
        )


        try:

            supabase.table(table)\
            .insert(data)\
            .execute()


            print(
                "DONE:",
                table,
                len(data)
            )


        except Exception as e:

            print(
                "FAILED:",
                table,
                e
            )
