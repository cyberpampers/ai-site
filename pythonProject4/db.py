import psycopg2

def get_connection():
    return psycopg2.connect(
        host="127.0.0.1",
        database="shop",
        user="postgres",
        password="1234",
        port=5432
    )
