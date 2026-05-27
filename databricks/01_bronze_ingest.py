# Databricks notebook source
# MAGIC %md
# MAGIC # Bronze ingest
# MAGIC
# MAGIC Loads the three raw inputs into Delta tables in the bronze layer, exactly as
# MAGIC they arrive, with no reshaping. This is the lakehouse equivalent of
# MAGIC `src/build_warehouse.py` loading the CSVs into SQLite.
# MAGIC
# MAGIC **Before running:** upload the three CSVs the local pipeline produced into the
# MAGIC Unity Catalog volume this notebook creates:
# MAGIC `employees.csv` (the real IBM file renamed, or `employees_sample.csv`),
# MAGIC `absence_events.csv`, and `recruitment.csv`.

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace")   # Free Edition ships the 'workspace' catalog
dbutils.widgets.text("schema", "workforce")
catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
print(f"Target: {catalog}.{schema}")

# COMMAND ----------

# Bronze, silver, and gold live as separate schemas under one catalog.
for layer in ("bronze", "silver", "gold"):
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.{layer}")

# A managed volume to hold the uploaded raw files.
spark.sql(f"CREATE VOLUME IF NOT EXISTS {catalog}.bronze.raw")
raw_path = f"/Volumes/{catalog}/bronze/raw"
print(f"Upload the CSVs to: {raw_path}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Load each file into a Delta bronze table

# COMMAND ----------

def ingest(file_name: str, table: str) -> None:
    df = (
        spark.read.option("header", True)
        .option("inferSchema", True)
        .csv(f"{raw_path}/{file_name}")
    )
    df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(
        f"{catalog}.bronze.{table}"
    )
    print(f"{catalog}.bronze.{table}: {df.count():,} rows")

ingest("employees.csv", "employees")
ingest("absence_events.csv", "absence")
ingest("recruitment.csv", "recruitment")

# COMMAND ----------

# MAGIC %md
# MAGIC Bronze is loaded. Continue with `02_silver_model`.
