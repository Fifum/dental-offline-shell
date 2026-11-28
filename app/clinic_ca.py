"""3.19: the clinic's own «certificate authority» — for the stock app with the scanner on the clinic's Wi-Fi.

A phone's browser gives the camera only to a secure page (https). A computer inside the clinic's Wi-Fi gets no certificate from
the internet's authorities (they certify names on the internet, not 192.168.x.x), so the program makes its own: a root
certificate of the clinic (installed once on a phone: «доверяй клинике») and the certificate of this computer, signed by it,
for its addresses. The root may certify only private addresses and local names (Name Constraints: 10/8, 172.16/12, 192.168/16,
169.254/16, 100.64/10, 127/8; .local, .lan, .home.arpa, .internal, localhost) — never a site of the internet, even if its key
were stolen. Both keys stay on this computer, encrypted (a random password kept with DPAPI, config.protect). The computer's
certificate is made again when its addresses change and a month before it ends (397 days: what iPhones accept).
"""
from __future__ import annotations

import datetime
import ipaddress
import logging
import plistlib
import secrets
import socket
import ssl
import threading
import uuid
from pathlib import Path

import config

log = logging.getLogger("clinic_ca")

CA_YEARS = 10
SERVER_DAYS = 397
RENEW_DAYS = 30
PERMITTED_NETS = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", "100.64.0.0/10", "127.0.0.0/8")
PERMITTED_DNS = ("local", "lan", "home.arpa", "internal", "localhost")
SETTING = "clinic_ca_pass"


def _x509():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
    return x509, hashes, serialization, ec, ExtendedKeyUsageOID, NameOID


def _cut(text: str, n=64) -> str:
    """A name of a certificate: at most 64 bytes in UTF-8 (a Cyrillic letter takes two)."""
    b = str(text).encode("utf-8")[:n]
    return b.decode("utf-8", "ignore").strip() or "Dental Desk"


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _private(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(a in ipaddress.ip_network(n) for n in PERMITTED_NETS)


def names_for(ips) -> tuple[list[str], list[str]]:
    """(addresses, names) the computer's certificate is for: its private addresses and 127.0.0.1; «<name>.local» and localhost
    (a bare computer name is left out: the root may not certify it, and one name it may not would spoil the certificate)."""
    addrs = sorted({ip for ip in list(ips or []) + ["127.0.0.1"] if _private(ip)}, key=lambda x: ipaddress.ip_address(x))
    host = "".join(ch for ch in socket.gethostname().lower() if ch.isalnum() or ch == "-").strip("-")
    names = ([f"{host}.local"] if host else []) + ["localhost"]
    return addrs, names


class ClinicCA:
    def __init__(self, folder=None, password=None):
        self.dir = Path(folder) if folder else config.data_dir() / "clinic_ca"
        self._password = password  # tests give their own; otherwise a random one kept with DPAPI
        self._lock = threading.RLock()
        self.ctx = None

    # ------------------------------------------------------------ files --
    def _pw(self) -> bytes:
        if self._password is None:
            s = config.load_settings()
            pw = config.unprotect(s.get(SETTING) or "")
            if not pw:
                pw = secrets.token_urlsafe(32)
                config.save_settings({SETTING: config.protect(pw)})
            self._password = pw
        return self._password.encode() if isinstance(self._password, str) else self._password

    def _p(self, name) -> Path:
        return self.dir / name

    def exists(self) -> bool:
        return self._p("ca.crt").exists() and self._p("ca.key").exists()

    def _save_key(self, key, name):
        _, _, serialization, _, _, _ = _x509()
        self.dir.mkdir(parents=True, exist_ok=True)
        self._p(name).write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                    serialization.BestAvailableEncryption(self._pw())))

    def _load_key(self, name):
        _, _, serialization, _, _, _ = _x509()
        return serialization.load_pem_private_key(self._p(name).read_bytes(), self._pw())

    def ca_cert(self):
        x509 = _x509()[0]
        return x509.load_pem_x509_certificate(self._p("ca.crt").read_bytes())

    def server_cert(self):
        x509 = _x509()[0]
        p = self._p("server.crt")
        return x509.load_pem_x509_certificate(p.read_bytes()) if p.exists() else None

    # --------------------------------------------------------- the root --
    def ensure_ca(self, title=""):
        """The root certificate of the clinic (made once on this computer)."""
        with self._lock:
            if self.exists():
                return self.ca_cert()
            x509, hashes, serialization, ec, _, NameOID = _x509()
            key = ec.generate_private_key(ec.SECP256R1())
            host = socket.gethostname()
            name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, _cut(title or f"Склад клиники — {host}")),
                              x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Dental Desk")])
            now = _now()
            nc = x509.NameConstraints(
                permitted_subtrees=[x509.IPAddress(ipaddress.ip_network(n)) for n in PERMITTED_NETS]
                + [x509.DNSName(d) for d in PERMITTED_DNS], excluded_subtrees=None)
            cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                    .serial_number(x509.random_serial_number())
                    .not_valid_before(now - datetime.timedelta(days=1))
                    .not_valid_after(now + datetime.timedelta(days=365 * CA_YEARS))
                    .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                    .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True, content_commitment=False,
                                                 key_encipherment=False, data_encipherment=False, key_agreement=False,
                                                 encipher_only=False, decipher_only=False), critical=True)
                    .add_extension(nc, critical=True)
                    .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
                    .sign(key, hashes.SHA256()))
            self._save_key(key, "ca.key")
            self._p("ca.crt").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            for f in ("server.crt", "server.key"):  # a new root: the old computer's certificate is of no use
                self._p(f).unlink(missing_ok=True)
            log.info("clinic CA made: %s", self.fingerprint())
            return cert

    def fingerprint(self) -> str:
        _, hashes, _, _, _, _ = _x509()
        return self.ca_cert().fingerprint(hashes.SHA256()).hex().upper() if self.exists() else ""

    # --------------------------------------------- the computer's certificate --
    def server_names(self):
        """(addresses, names) of the current certificate of this computer."""
        x509 = _x509()[0]
        c = self.server_cert()
        if c is None:
            return [], []
        san = c.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        return sorted(str(a) for a in san.get_values_for_type(x509.IPAddress)), sorted(san.get_values_for_type(x509.DNSName))

    def needs_new(self, ips) -> bool:
        c = self.server_cert()
        if c is None or not self._p("server.key").exists():
            return True
        addrs, names = names_for(ips)
        have_a, have_n = self.server_names()
        left = c.not_valid_after_utc - _now()
        return sorted(addrs) != have_a or sorted(names) != have_n or left < datetime.timedelta(days=RENEW_DAYS)

    def ensure_server(self, ips) -> bool:
        """The certificate of this computer for its current addresses; True when a new one was made."""
        with self._lock:
            self.ensure_ca()
            if not self.needs_new(ips):
                return False
            x509, hashes, serialization, ec, EKU, NameOID = _x509()
            ca_key, ca = self._load_key("ca.key"), self.ca_cert()
            addrs, names = names_for(ips)
            key = ec.generate_private_key(ec.SECP256R1())
            now = _now()
            cn = addrs[0] if addrs and addrs[0] != "127.0.0.1" else (names[0] if names else "localhost")
            cert = (x509.CertificateBuilder()
                    .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)]))
                    .issuer_name(ca.subject).public_key(key.public_key()).serial_number(x509.random_serial_number())
                    .not_valid_before(now - datetime.timedelta(hours=1)).not_valid_after(now + datetime.timedelta(days=SERVER_DAYS))
                    .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(a)) for a in addrs]
                                                               + [x509.DNSName(n) for n in names]), critical=False)
                    .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                    .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=False, crl_sign=False,
                                                 content_commitment=False, key_encipherment=False, data_encipherment=False,
                                                 key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
                    .add_extension(x509.ExtendedKeyUsage([EKU.SERVER_AUTH]), critical=False)
                    .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
                    .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
                    .sign(ca_key, hashes.SHA256()))
            self._save_key(key, "server.key")
            self._p("server.crt").write_bytes(cert.public_bytes(serialization.Encoding.PEM) + ca.public_bytes(serialization.Encoding.PEM))
            log.info("certificate of this computer made for %s %s", addrs, names)
            if self.ctx is not None:  # the running https server takes the new one for new connections
                self.ctx.load_cert_chain(str(self._p("server.crt")), str(self._p("server.key")), self._pw())
            return True

    def ssl_context(self, ips):
        with self._lock:
            self.ensure_server(ips)
            if self.ctx is None:
                ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                ctx.minimum_version = ssl.TLSVersion.TLSv1_2
                ctx.load_cert_chain(str(self._p("server.crt")), str(self._p("server.key")), self._pw())
                self.ctx = ctx
            return self.ctx

    # ------------------------------------------------------ for the phones --
    def ca_der(self) -> bytes:
        _, _, serialization, _, _, _ = _x509()
        return self.ca_cert().public_bytes(serialization.Encoding.DER)

    def ca_pem(self) -> bytes:
        return self._p("ca.crt").read_bytes()

    def title(self) -> str:
        from cryptography.x509.oid import NameOID
        a = self.ca_cert().subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        return a[0].value if a else "Dental Desk — клиника"

    def mobileconfig(self) -> bytes:
        """The profile an iPhone installs the root certificate from (Settings → «Профиль загружен» → «Установить»)."""
        fp = self.fingerprint()
        u1, u2 = (str(uuid.uuid5(uuid.NAMESPACE_URL, f"dentaldesk:clinic-ca:{fp}:{i}")).upper() for i in (1, 2))
        name = self.title()
        return plistlib.dumps({
            "PayloadContent": [{
                "PayloadCertificateFileName": "dental-desk-clinic.cer", "PayloadContent": self.ca_der(),
                "PayloadDescription": "Сертификат клиники: склад на телефоне со сканером через Wi-Fi клиники.",
                "PayloadDisplayName": name, "PayloadIdentifier": f"com.dentaldesk.clinic-ca.{u1}",
                "PayloadType": "com.apple.security.root", "PayloadUUID": u1, "PayloadVersion": 1}],
            "PayloadDescription": "Склад клиники со сканером через Wi-Fi клиники. Сертификат годится только для адресов внутри "
                                  "сети клиники, ключ хранится на компьютере клиники.",
            "PayloadDisplayName": "Склад клиники — сертификат", "PayloadIdentifier": f"com.dentaldesk.clinic.{u2}",
            "PayloadOrganization": "Dental Desk", "PayloadRemovalDisallowed": False, "PayloadType": "Configuration",
            "PayloadUUID": u2, "PayloadVersion": 1}, fmt=plistlib.FMT_XML)

    def state(self) -> dict:
        if not self.exists():
            return {"ca": False}
        c = self.server_cert()
        addrs, names = self.server_names()
        return {"ca": True, "title": self.title(), "fingerprint": self.fingerprint(),
                "short": " ".join(self.fingerprint()[i:i + 4] for i in range(0, 16, 4)),
                "addresses": addrs, "names": names,
                "until": c.not_valid_after_utc.strftime("%d.%m.%Y") if c is not None else ""}


_CA = None


def get() -> ClinicCA:
    global _CA
    if _CA is None:
        _CA = ClinicCA()
    return _CA

