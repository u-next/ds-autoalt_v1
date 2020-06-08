select
sakuhin_public_code,
episode_public_code,
product_episode_code,
sakuhin_name,
episode_name,
episode_no,
sale_start_datetime
from public.dim_product
where sale_start_datetime > now() - INTERVAL '7 day'
and sale_start_datetime <= now()
and sakuhin_public_code like 'SID%'
order by episode_no