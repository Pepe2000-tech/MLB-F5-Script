-- MLB Betting Hub V7 - almacenamiento persistente de Paper Bets
create table if not exists public.mlb_paper_bets (
  paper_id text primary key,
  created_at timestamptz not null default now(),
  payload jsonb not null
);

alter table public.mlb_paper_bets enable row level security;

-- Para uso personal rápido con la anon key del proyecto.
-- Si después compartes la app con terceros, reemplaza esta política por autenticación real.
create policy "personal paper bets read"
on public.mlb_paper_bets for select
using (true);

create policy "personal paper bets insert"
on public.mlb_paper_bets for insert
with check (true);

create policy "personal paper bets update"
on public.mlb_paper_bets for update
using (true)
with check (true);

create policy "personal paper bets delete"
on public.mlb_paper_bets for delete
using (true);
