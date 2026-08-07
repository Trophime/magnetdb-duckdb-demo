from _common import *




def main():

    con = duckdb.connect(DB)

    df = con.execute(
        """
            SELECT *
            FROM housing_summary
            WHERE 
                research_area IS NOT NULL
                AND field_max IS NOT NULL
                AND field_mean IS NOT NULL
                AND field_std IS NOT NULL
                AND field_median IS NOT NULL
                AND field_time_on IS NOT NULL
        """
    ).fetchdf()

    print(f"Loaded {len(df)} experiment records from housing_summary")

    columns = ["field_max", "field_mean",  
               "field_std", "field_median",
               "field_time_on"]

    con.close()