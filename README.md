# DCGGSRRJPJ Stack App

We use to have LAMP (Linux Apache MySQL PHP), now we have DCGGSRRJPJ

Docker Caddy Gevent Gunicorn Flask SocketIO Redis RedisQueue Jinja2 Python Javascript

### Restart
```
docker compose -f docker-compose.nocaddy.yml down
docker compose -f docker-compose.nocaddy.yml up -d --build  --scale rq-worker=4
```



### Low Level Redis 0 DB Monitoring
```
docker exec -it dcggsrrjpj-app-redis-1 sh
redis-cli -n 0 MONITOR
```

### RQ Worker Pool Aggregated logs
```
docker compose logs -f rq-worker
```