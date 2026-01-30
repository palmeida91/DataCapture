"""
Generate self-signed certificates for OPC UA client
"""

from cryptography import x509
from cryptography.x509.oid import NameOID, ExtensionOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from datetime import datetime, timedelta
import ipaddress
import socket

# Generate private key
print("Generating RSA key pair...")
private_key = rsa.generate_private_key(
    public_exponent=65537,
    key_size=2048,
)

# Get local hostname
hostname = socket.gethostname()

# Certificate details
subject = issuer = x509.Name([
    x509.NameAttribute(NameOID.COUNTRY_NAME, u"DE"),
    x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, u"State"),
    x509.NameAttribute(NameOID.LOCALITY_NAME, u"City"),
    x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"ProductionMonitoring"),
    x509.NameAttribute(NameOID.COMMON_NAME, u"ProductionClient"),
])

# Generate certificate
print("Generating certificate...")
cert = x509.CertificateBuilder().subject_name(
    subject
).issuer_name(
    issuer
).public_key(
    private_key.public_key()
).serial_number(
    x509.random_serial_number()
).not_valid_before(
    datetime.utcnow()
).not_valid_after(
    datetime.utcnow() + timedelta(days=3650)  # 10 years
).add_extension(
    x509.SubjectAlternativeName([
        x509.DNSName(u"localhost"),
        x509.DNSName(hostname),
        x509.IPAddress(ipaddress.IPv4Address(u"127.0.0.1")),
        x509.UniformResourceIdentifier(u"urn:ProductionMonitoring:OpcuaClient"),
    ]),
    critical=False,
).add_extension(
    x509.BasicConstraints(ca=False, path_length=None),
    critical=True,
).add_extension(
    x509.KeyUsage(
        digital_signature=True,
        key_encipherment=True,
        data_encipherment=True,
        key_agreement=False,
        content_commitment=False,
        key_cert_sign=False,
        crl_sign=False,
        encipher_only=False,
        decipher_only=False,
    ),
    critical=True,
).sign(private_key, hashes.SHA256())

# Write private key
print("Writing files...")
with open("client_key.pem", "wb") as f:
    f.write(private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption()
    ))

# Write certificate in PEM format
with open("client_cert.pem", "wb") as f:
    f.write(cert.public_bytes(serialization.Encoding.PEM))

# Write certificate in DER format (for asyncua)
with open("client_cert.der", "wb") as f:
    f.write(cert.public_bytes(serialization.Encoding.DER))

print("")
print("[OK] Certificates generated successfully!")
print("")
print("Files created:")
print("  - client_key.pem      (Private key)")
print("  - client_cert.pem     (Certificate - PEM format)")
print("  - client_cert.der     (Certificate - DER format)")
print("")
print("Certificate details:")
print(f"  Application URI: urn:ProductionMonitoring:OpcuaClient")
print(f"  DNS Names: localhost, {hostname}")
print(f"  Valid for: 10 years")
