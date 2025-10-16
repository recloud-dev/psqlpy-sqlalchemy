docker run --rm -e POSTGRES_USER='scott' -e POSTGRES_PASSWORD='tiger' -e POSTGRES_DB='test' -p 127.0.0.1:5432:5432 -d --name postgres postgres
sleep 10
docker exec -ti postgres psql -U scott -c 'CREATE SCHEMA test_schema; CREATE SCHEMA test_schema_2;CREATE EXTENSION hstore;CREATE EXTENSION citext;' test