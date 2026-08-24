# Pounce
Physics Based College Football Game

## Run the upload server

```bash
python server.py
```

Then open `http://127.0.0.1:8000`, upload an `.html` game file, and the server will redirect you to the hosted game.

The server binds to `127.0.0.1` by default. If you need it accessible from other machines, set `POUNCE_HOST=0.0.0.0` explicitly before starting it.
