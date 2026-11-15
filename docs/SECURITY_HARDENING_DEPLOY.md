# Despliegue de las correcciones de seguridad

Los cambios de código y la migración deben desplegarse juntos. No se debe
desplegar la Edge Function antes de configurar el secreto, porque ahora falla
al iniciar si el secreto falta o tiene menos de 32 caracteres.

## 1. Confirmar el secreto

Confirma en el gestor de secretos que `XENS_TOKEN_SECRET` existe y tiene al
menos 32 caracteres. Si cumple, consérvalo: no hace falta invalidar sesiones.
Si falta o es más corto, genera uno en un equipo seguro y guárdalo directamente
en Supabase; **no lo compartas por chat ni lo guardes en el repositorio**.

```powershell
$secret = [Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(48))
supabase secrets set "XENS_TOKEN_SECRET=$secret" --project-ref tzlbgoydgptlhspzdhfu
Remove-Variable secret
```

Al cambiar `XENS_TOKEN_SECRET`, los tokens de licencia existentes dejan de ser
válidos y los clientes tendrán que volver a activar su licencia/iniciar sesión.

## 2. Aplicar y desplegar

Desde la raíz del repositorio:

```powershell
supabase db push --project-ref tzlbgoydgptlhspzdhfu
supabase functions deploy license --project-ref tzlbgoydgptlhspzdhfu
```

Despliega también la Web que contiene las cabeceras de seguridad.

## 3. Verificar permisos y comportamiento

En el SQL Editor de Supabase, confirma que ambas expresiones son `false`:

```sql
select
  has_function_privilege('anon', 'public.get_user_credits(text,text)', 'EXECUTE') as anon_can_read_credits,
  has_function_privilege('authenticated', 'public.get_user_credits(text,text)', 'EXECUTE') as user_can_read_credits,
  has_function_privilege('anon', 'public.try_spend_user_credits(text,text,integer,integer)', 'EXECUTE') as anon_can_spend,
  has_function_privilege('authenticated', 'public.try_reserve_free_chat(uuid,text,integer)', 'EXECUTE') as user_can_reserve_free_chat,
  has_function_privilege('service_role', 'public.try_spend_user_credits(text,text,integer,integer)', 'EXECUTE') as server_can_spend;
```

También verifica:

- `/credits-check` sin token responde `401`.
- `/credits-spend` responde `410`; el cliente no puede declarar consumo.
- Un usuario autenticado no puede leer ni gastar créditos de otro UID.
- Chats Free concurrentes no exceden el límite configurado.
- Una cuenta sin suscripción activa recibe el plan `free`.
- Más de 20 solicitudes de provisión desde una misma IP en 24 horas reciben `429`.
- El endpoint `deactivate` sin token de licencia responde `401`.
- `XENS_TOKEN_SECRET` existe en Edge Secrets y tiene al menos 32 caracteres.

La aplicación local puede ejecutar pruebas de Edge sin credenciales. Las pruebas
contra Supabase requieren el proyecto desplegado y una cuenta/licencia de prueba.
