# Dental Desk cloud server

One Python file, standard library only (Python 3.10+). It keeps encrypted rows for many clinics and never sees
their data: rows are encrypted on the clinic's laptops (AES-256-GCM) and stored under HMAC names.

## Try it locally

```powershell
python cloud\cloud_server.py --data .\cloud-data serve --port 8780
python cloud\cloud_server.py --data .\cloud-data create-tenant "Test clinic"   # prints the connection code
```

In the program: Settings → «Облако и подписка» → address `http://127.0.0.1:8780` and the code.
Plain `http://` is accepted only for 127.0.0.1; a real server must be `https://`.

## On a VPS (Ubuntu, nginx, Let's Encrypt)

```bash
sudo useradd -r -m -d /opt/ddcloud ddcloud
sudo -u ddcloud mkdir -p /opt/ddcloud/data && sudo cp cloud_server.py /opt/ddcloud/
sudo tee /etc/systemd/system/ddcloud.service >/dev/null <<'EOF'
[Unit]
Description=Dental Desk cloud
After=network.target
[Service]
User=ddcloud
ExecStart=/usr/bin/python3 /opt/ddcloud/cloud_server.py --data /opt/ddcloud/data serve --host 127.0.0.1 --port 8780
Restart=always
[Install]
WantedBy=multi-user.target
EOF
sudo systemctl enable --now ddcloud
```

nginx site (then `sudo certbot --nginx -d cloud.example.ru`):

```nginx
server {
    server_name cloud.example.ru;
    client_max_body_size 40m;
    location / { proxy_pass http://127.0.0.1:8780; proxy_set_header Host $host; proxy_read_timeout 120s; }
}
```

Back up `/opt/ddcloud/data` (control.db, one `<tenant>.db` and one `<tenant>.blobs` folder per clinic) every night.
For data localisation run one server per country (RU, KZ, UZ) — the program only needs the address.

## Clinics and payments

```bash
python3 cloud_server.py --data data create-tenant "Clinic name"            # 30-day trial, prints the code
python3 cloud_server.py --data data pay <tenant> --plan clinic --months 1 --amount 5900
python3 cloud_server.py --data data list                                   # clinics, plans, devices, paid till
python3 cloud_server.py --data data devices <tenant>
python3 cloud_server.py --data data revoke <device>
python3 cloud_server.py --data data new-invite <tenant>                    # the old code stops working
```

Plans: Старт (3 computers, 2 900 ₽/month), Клиника (10, 5 900 ₽), Сеть клиник (50, 11 900 ₽). After the paid date
there are 7 days of grace, then sync pauses (the laptops keep working) until the next payment.

## API (JSON over HTTPS, `Authorization: Bearer <device token>`)

| | |
|---|---|
| `POST /v1/join` | invite code + computer name → device token, clinic, key check |
| `POST /v1/key_check` | first computer stores an HMAC of the clinic key (set once) |
| `POST /v1/status` | subscription, devices of the clinic |
| `POST /v1/push` | `[{key, ver, base, data}]` — accepted only if `base` is the current version |
| `POST /v1/pull` | rows changed after `since` (sequence number), 500 per page |
| `PUT/GET /v1/blob/<id>`, `POST /v1/blob_has` | encrypted files (X-rays) |
| `POST /v1/leave`, `POST /v1/revoke` | switch off this or another computer of the same clinic |
