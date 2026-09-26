# Firma del exe (SmartScreen)

Sin firma, Windows muestra “Windows protegió su PC” en cada descarga.
Con firma + reputación, el aviso desaparece.

## Estado actual

- El exe ya lleva metadatos (`scripts/version_info.txt`: empresa SvY Teck,
  producto AINSLUP Assistant). Eso ayuda pero **no sustituye** la firma.
- `scripts/sign_exe.py` firma si hay certificado; sin él sale con
  instrucciones y código 2 (el build no se rompe).

## Conseguir el certificado (acción del owner, con tarjeta)

Opción A — Certificado OV (~150–400 €/año, Sectigo/DigiCert vía reseller
como SSL.com). Llega un PFX:
```cmd
set AINSLUP_SIGN_PASSWORD=***
python scripts/sign_exe.py dist/Ainslup.exe --pfx ruta\cert.pfx
```

Opción B — Azure Trusted Signing (pago por firma, sin anualidad alta).
Requiere cuenta Azure + identidad validada; luego se firma con
`AzureSignTool` (ver variables `AINSLUP_AZURE_*` en el script).

## Reputación SmartScreen

Aun firmado, SmartScreen desconfía los primeros días/descargas hasta que
el binario gana reputación. Publicar siempre el mismo nombre
(`Ainslup.exe`) y no cambiar el certificado acelera el proceso.
