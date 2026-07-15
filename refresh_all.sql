-- ============================================================================
-- refresh_all.sql — MINDEN SZÁMÍTOTT RÉTEG ÚJRAÉPÍTÉSE (függőségi sorrendben)
-- Előfeltétel: nyers táblák frissek (fund_nav, risk_free, fx_rate, fund_ter, fund_peer_group).
-- Sorrend: hozamok -> forgalom -> vol+drawdown -> Sharpe/Sortino -> likviditás -> gold -> piaci AUM+forgalom
-- psql-lel futtatva NINCS webes időtúllépés. Minden lépés drop+create → bármikor újrafuttatható.
-- ============================================================================

drop view if exists v_fund_full;
drop view if exists v_fund_latest;


-- >>>>>>>>>>>>>>>>>> 1_hozamok.sql <<<<<<<<<<<<<<<<<<

-- Előkészítés: a több táblától függő kereszt-nézetek eldobása (a gold lépés újra létrehozza)
drop view if exists v_fund_full;
drop view if exists v_fund_latest;

-- =====================================================================
-- Napi visszatekintő hozamok minden alapra, minden napra
-- Forrás: fund_nav.price (egy jegyre jutó árfolyam)
-- Az értékek TIZEDES TÖRTBEN:  0.036 = 3,6%
-- =====================================================================

-- hosszabb futásidő engedélyezése (nagy tábla, pár perc lehet)
set statement_timeout to '900s';

-- újrafuttatható: előbb a függő nézet, majd a tábla eldobása
drop view  if exists v_fund_returns;
drop table if exists fund_returns_daily;

create table fund_returns_daily as
select
  n.fund_id,
  n.obs_date,
  -- YTD: az idei ár / az előző év utolsó ára - 1
  n.price / pytd.price - 1                          as ytd,
  -- 1 éves visszatekintő
  n.price / p1y.price  - 1                          as r_1y,
  -- 3 éves visszatekintő, ÉVESÍTVE (CAGR)
  power(n.price / p3y.price, 1.0/3.0) - 1           as r_3y_ann,
  -- 6 havi visszatekintő, ÉVESÍTVE (fél év -> teljes évre vetítve)
  power(n.price / p6m.price, 1.0/0.5) - 1           as r_6m_ann
from fund_nav n
-- YTD bázis: az előző év utolsó elérhető ára
left join lateral (
  select price from fund_nav b
  where b.fund_id = n.fund_id
    and b.obs_date < date_trunc('year', n.obs_date)::date
    and b.price is not null
  order by b.obs_date desc limit 1
) pytd on true
-- 1 évvel ezelőtti (vagy az azt megelőző utolsó) ár
left join lateral (
  select price from fund_nav b
  where b.fund_id = n.fund_id
    and b.obs_date <= (n.obs_date - interval '1 year')::date
    and b.price is not null
  order by b.obs_date desc limit 1
) p1y on true
-- 3 évvel ezelőtti ár
left join lateral (
  select price from fund_nav b
  where b.fund_id = n.fund_id
    and b.obs_date <= (n.obs_date - interval '3 years')::date
    and b.price is not null
  order by b.obs_date desc limit 1
) p3y on true
-- 6 hónappal ezelőtti ár
left join lateral (
  select price from fund_nav b
  where b.fund_id = n.fund_id
    and b.obs_date <= (n.obs_date - interval '6 months')::date
    and b.price is not null
  order by b.obs_date desc limit 1
) p6m on true
where n.price is not null;

-- kulcs + index + olvasási jog
alter table fund_returns_daily add primary key (fund_id, obs_date);
create index idx_frd_date on fund_returns_daily (obs_date);
grant select on fund_returns_daily to anon, authenticated;

-- kényelmi nézet: hozamok alapnévvel együtt (Excelhez / diagramokhoz)
create or replace view v_fund_returns
with (security_invoker = true) as
select d.isin, d.name, d.manager, d.category, d.currency,
       r.obs_date, r.ytd, r.r_1y, r.r_3y_ann, r.r_6m_ann
from fund_returns_daily r
join fund_dim d using (fund_id);
grant select on v_fund_returns to anon, authenticated;

-- >>>>>>>>>>>>>>>>>> 2_forgalom.sql <<<<<<<<<<<<<<<<<<

-- =====================================================================
-- Gördülő forgalmi (nettó tőkeáramlási) mutatók minden alapra, minden napra
-- Forrás: fund_nav.turnover (napi nettó befektetésijegy-forgalom; - = kiáramlás)
--
--   turnover_cum_30d : az elmúlt 30 nap kumulált forgalma
--   turnover_avg_30d : az elmúlt 30 nap átlagos NAPI forgalma (kumulált / keresk. napok)
--   turnover_cum_1y  : az elmúlt 1 év kumulált forgalma
--   turnover_avg_1y  : az elmúlt 1 év átlagos NAPI forgalma
--
-- "Elmúlt 30 nap" = az adott napot megelőző 30 naptári nap + az adott nap.
-- Az átlag NAPI = kumulált / az ablakba eső kereskedési napok száma.
-- =====================================================================

set statement_timeout to '600s';

drop view  if exists v_fund_flows;
drop table if exists fund_flows_daily;

create table fund_flows_daily as
select
  fund_id,
  obs_date,
  sum(turnover) over w30                                        as turnover_cum_30d,
  sum(turnover) over w30 / nullif(count(turnover) over w30, 0)  as turnover_avg_30d,
  sum(turnover) over w1y                                        as turnover_cum_1y,
  sum(turnover) over w1y / nullif(count(turnover) over w1y, 0)  as turnover_avg_1y
from fund_nav
where turnover is not null
window
  w30 as (partition by fund_id order by obs_date
          range between interval '30 days' preceding and current row),
  w1y as (partition by fund_id order by obs_date
          range between interval '1 year'  preceding and current row);

alter table fund_flows_daily add primary key (fund_id, obs_date);
create index idx_ffd_date on fund_flows_daily (obs_date);
grant select on fund_flows_daily to anon, authenticated;

-- kényelmi nézet: forgalmi mutatók alapnévvel együtt (Excelhez / diagramokhoz)
create or replace view v_fund_flows
with (security_invoker = true) as
select d.isin, d.name, d.manager, d.category, d.currency,
       f.obs_date,
       f.turnover_cum_30d, f.turnover_avg_30d,
       f.turnover_cum_1y,  f.turnover_avg_1y
from fund_flows_daily f
join fund_dim d using (fund_id);
grant select on v_fund_flows to anon, authenticated;

-- >>>>>>>>>>>>>>>>>> 3_kockazat.sql <<<<<<<<<<<<<<<<<<

-- =====================================================================
-- 7. szakasz — Kockázati mutatók a napi árfolyamból
--   A) fund_vol_daily : napi 1 ÉVES VOLATILITÁS (évesített), minden napra
--   B) fund_drawdown  : MAX DRAWDOWN és annak hossza, alaponként (utolsó 5 év
--                       vagy az adatsor kezdete óta)
-- Értékek tizedes törtben: 0.19 = 19%.
-- =====================================================================

set statement_timeout to '900s';

-- ---------------------------------------------------------------------
-- A) NAPI 1 ÉVES VOLATILITÁS
--    = a napi hozamok szórása a gördülő 1 éves ablakban, évesítve (×√252)
--    Csak akkor számoljuk, ha legalább 200 napi hozam van az ablakban.
-- ---------------------------------------------------------------------
drop view  if exists v_fund_vol;
drop table if exists fund_vol_daily;

create table fund_vol_daily as
with rets as (
  select fund_id, obs_date,
         price / lag(price) over (partition by fund_id order by obs_date) - 1 as r
  from fund_nav
  where price is not null
)
select fund_id, obs_date,
       case when count(r) over w >= 200
            then stddev_samp(r) over w * sqrt(252)
       end as vol_1y
from rets
window w as (partition by fund_id order by obs_date
            range between interval '1 year' preceding and current row);

alter table fund_vol_daily add primary key (fund_id, obs_date);
create index idx_fvd_date on fund_vol_daily (obs_date);
grant select on fund_vol_daily to anon, authenticated;

create or replace view v_fund_vol
with (security_invoker = true) as
select d.isin, d.name, d.manager, d.category, d.currency,
       v.obs_date, v.vol_1y
from fund_vol_daily v join fund_dim d using (fund_id);
grant select on v_fund_vol to anon, authenticated;

-- ---------------------------------------------------------------------
-- B) MAX DRAWDOWN + HOSSZ  (alaponként, az utolsó 5 évre / adatsor kezdetétől)
--    max_drawdown : legnagyobb csúcs->mély esés (negatív szám)
--    peak_date    : a mélységet megelőző csúcs dátuma
--    trough_date  : a mélypont dátuma
--    decline_days : csúcs -> mély (a drawdown levonulási hossza, napokban)
--    recovery_date: első nap a mély után, amikor az ár visszaéri a csúcsot
--                   (NULL, ha még nem állt helyre)
--    recovery_days: csúcs -> recovery (teljes "víz alatti" hossz)
-- ---------------------------------------------------------------------
drop view  if exists v_fund_drawdown;
drop table if exists fund_drawdown;

create table fund_drawdown as
with dd as (
  select fund_id, obs_date, price,
         max(price) over (partition by fund_id order by obs_date
                          rows between unbounded preceding and current row) as peak
  from fund_nav
  where price is not null
    and obs_date >= (current_date - interval '5 years')::date
),
ddd as (
  select fund_id, obs_date, price, peak, price/peak - 1 as drawdown from dd
),
trough as (   -- a legmélyebb pont alaponként
  select distinct on (fund_id)
         fund_id, obs_date as trough_date, peak as peak_price, drawdown as max_drawdown
  from ddd
  order by fund_id, drawdown asc, obs_date asc
),
peakd as (    -- a csúcs dátuma: utolsó nap a mély előtt/azon, ahol ár >= peak_price
  select distinct on (d.fund_id) d.fund_id, d.obs_date as peak_date
  from ddd d join trough t on t.fund_id = d.fund_id
  where d.obs_date <= t.trough_date and d.price >= t.peak_price
  order by d.fund_id, d.obs_date desc
),
recov as (    -- első nap a mély után, ahol ár >= peak_price
  select distinct on (d.fund_id) d.fund_id, d.obs_date as recovery_date
  from ddd d join trough t on t.fund_id = d.fund_id
  where d.obs_date > t.trough_date and d.price >= t.peak_price
  order by d.fund_id, d.obs_date asc
)
select t.fund_id,
       t.max_drawdown,
       p.peak_date,
       t.trough_date,
       (t.trough_date - p.peak_date)                    as decline_days,
       r.recovery_date,
       (r.recovery_date - p.peak_date)                  as recovery_days
from trough t
join peakd p using (fund_id)
left join recov r using (fund_id);

alter table fund_drawdown add primary key (fund_id);
grant select on fund_drawdown to anon, authenticated;

create or replace view v_fund_drawdown
with (security_invoker = true) as
select d.isin, d.name, d.manager, d.category, d.currency,
       dr.max_drawdown, dr.peak_date, dr.trough_date,
       dr.decline_days, dr.recovery_date, dr.recovery_days
from fund_drawdown dr join fund_dim d using (fund_id);
grant select on v_fund_drawdown to anon, authenticated;

-- >>>>>>>>>>>>>>>>>> 4_sharpe_sortino.sql <<<<<<<<<<<<<<<<<<

-- =====================================================================
-- 9. szakasz — Napi 1 éves SHARPE és SORTINO, minden alapra
--   Sharpe  = (1 éves hozam - kockázatmentes) / 1 éves volatilitás
--   Sortino = (1 éves hozam - kockázatmentes) / lefelé-szórás (target=0, évesítve)
-- A kockázatmentes ráta az alap DEVIZÁJA szerint, AS-OF illesztéssel:
--   az adott napon vagy azt megelőzően legutóbb elérhető ráta.
-- Ahol a devizához nincs ráta (CZK/PLN/CHF), ott a mutatók NULL-ok maradnak.
-- =====================================================================

set statement_timeout to '900s';

drop view  if exists v_fund_ratios;
drop table if exists fund_ratios_daily;

create table fund_ratios_daily as
with rets as (
  select fund_id, obs_date,
         price / lag(price) over (partition by fund_id order by obs_date) - 1 as r
  from fund_nav
  where price is not null
),
dd as (   -- lefelé-szórás (downside deviation), gördülő 1 év, target=0, évesítve
  select fund_id, obs_date,
         case when count(r) over w >= 200
              then sqrt( sum(power(least(r,0),2)) over w / count(r) over w ) * sqrt(252)
         end as downside_dev
  from rets
  window w as (partition by fund_id order by obs_date
              range between interval '1 year' preceding and current row)
),
rf as (   -- as-of kockázatmentes ráta az alap devizájában (legfrissebb elérhető)
  select ret.fund_id, ret.obs_date,
    (select r.rate from risk_free r
      where r.currency = d.currency and r.obs_date <= ret.obs_date
      order by r.obs_date desc limit 1) as rf_rate
  from fund_returns_daily ret
  join fund_dim d using (fund_id)
)
select
  ret.fund_id,
  ret.obs_date,
  rf.rf_rate,
  case when v.vol_1y > 0
       then (ret.r_1y - rf.rf_rate) / v.vol_1y end                       as sharpe_1y,
  case when dd.downside_dev > 0
       then (ret.r_1y - rf.rf_rate) / dd.downside_dev end                as sortino_1y
from fund_returns_daily ret
join fund_vol_daily v  using (fund_id, obs_date)
left join dd           using (fund_id, obs_date)
left join rf           using (fund_id, obs_date);

alter table fund_ratios_daily add primary key (fund_id, obs_date);
create index idx_fratios_date on fund_ratios_daily (obs_date);
grant select on fund_ratios_daily to anon, authenticated;

create or replace view v_fund_ratios
with (security_invoker = true) as
select d.isin, d.name, d.manager, d.category, d.currency,
       r.obs_date, r.rf_rate, r.sharpe_1y, r.sortino_1y
from fund_ratios_daily r join fund_dim d using (fund_id);
grant select on v_fund_ratios to anon, authenticated;

-- >>>>>>>>>>>>>>>>>> 5_likviditas.sql <<<<<<<<<<<<<<<<<<

-- =====================================================================
-- 11. szakasz — Illikvid / potenciálisan zárt alapok jelölése
-- Jelek:
--   days_stale        : hány nappal marad el az alap utolsó adata a piac
--                       legfrissebb napjától (nagy = inaktív/megszűnt)
--   turnover_days_180 : hány napon van FORGALMI ADAT az utolsó 180 napban
--   active_ratio_180  : ezekből hány százalékon volt NEM-NULLA forgalom
--
-- is_illiquid = TRUE, ha:
--   - days_stale > 30 (inaktív/megszűnt), VAGY
--   - van elég forgalmi adat (>=20 nap) és az aktív arány < 10% (dormant)
-- Ahol nincs forgalmi adat, azt NEM jelöljük illikvidnek.
-- =====================================================================

set statement_timeout to '600s';

drop view  if exists v_fund_liquidity;
drop table if exists fund_liquidity;

create table fund_liquidity as
with ref as (select max(obs_date) as ref_date from fund_nav),
agg as (
  select
    n.fund_id,
    max(n.obs_date) as last_obs_date,
    count(*) filter (
      where n.obs_date > (select ref_date from ref) - interval '180 days'
        and n.price is not null)                                as trading_days_180,
    count(*) filter (
      where n.obs_date > (select ref_date from ref) - interval '180 days'
        and n.turnover is not null)                             as turnover_days_180,
    count(*) filter (
      where n.obs_date > (select ref_date from ref) - interval '180 days'
        and n.turnover is not null and n.turnover <> 0)         as nonzero_180,
    avg(abs(n.turnover)) filter (
      where n.obs_date > (select ref_date from ref) - interval '180 days') as avg_abs_turnover_180
  from fund_nav n
  group by n.fund_id
),
latest_aum as (
  select distinct on (fund_id) fund_id, nav as latest_aum
  from fund_nav where nav is not null
  order by fund_id, obs_date desc
)
select
  a.fund_id,
  a.last_obs_date,
  ((select ref_date from ref) - a.last_obs_date)                as days_stale,
  a.trading_days_180,
  a.turnover_days_180,
  a.nonzero_180,
  case when a.turnover_days_180 > 0
       then a.nonzero_180::numeric / a.turnover_days_180 end    as active_ratio_180,
  a.avg_abs_turnover_180,
  la.latest_aum,
  (
        ((select ref_date from ref) - a.last_obs_date) > 30
     or a.trading_days_180 = 0
     or (a.turnover_days_180 >= 20
         and a.nonzero_180::numeric / a.turnover_days_180 < 0.10)
  )                                                             as is_illiquid,
  case
    when ((select ref_date from ref) - a.last_obs_date) > 30
      or a.trading_days_180 = 0                              then 'inaktív/megszűnt'
    when a.turnover_days_180 >= 20
      and a.nonzero_180::numeric / a.turnover_days_180 < 0.10 then 'illikvid/dormant'
    when a.turnover_days_180 = 0                             then 'nincs forgalmi adat'
    else 'aktív'
  end                                                          as status
from agg a
left join latest_aum la using (fund_id);

alter table fund_liquidity add primary key (fund_id);
grant select on fund_liquidity to anon, authenticated;

create or replace view v_fund_liquidity
with (security_invoker = true) as
select d.isin, d.name, d.manager, d.category, d.currency,
       l.last_obs_date, l.days_stale, l.trading_days_180, l.turnover_days_180,
       l.active_ratio_180, l.avg_abs_turnover_180, l.latest_aum,
       l.is_illiquid, l.status
from fund_liquidity l join fund_dim d using (fund_id);
grant select on v_fund_liquidity to anon, authenticated;

-- >>>>>>>>>>>>>>>>>> 6_gold.sql <<<<<<<<<<<<<<<<<<

-- =====================================================================
-- 12c. szakasz — Gold réteg: + series, + HUF oszlopok, + drawdown dátumok, + peer group
-- Előfeltétel: az fx_rate tábla fel van töltve (Árfolyam workflow lefutott).
--   fund_latest : 1 sor/alap, legfrissebb értékek + aum_huf + forgalom HUF-ban
--   v_fund_full : teljes napi idősor (+ series)
-- =====================================================================

set statement_timeout to '600s';

-- ---------------------------------------------------------------------
-- A) fund_latest
-- ---------------------------------------------------------------------
drop view  if exists v_fund_latest;
drop table if exists fund_latest;

create table fund_latest as
with last_date as (
  select fund_id, max(obs_date) as d
  from fund_nav where price is not null
  group by fund_id
)
select
  d.fund_id, d.isin, d.name, d.series, d.manager, d.category, d.currency,
  d.launch_date, d.legal_type, d.geo_exposure, d.esg, d.risk_return,
  ld.d                                   as obs_date,
  n.price, n.nav, n.turnover,
  coalesce(n.nav, liq.latest_aum)        as aum,
  fx.huf_per_unit,
  coalesce(n.nav, liq.latest_aum) * fx.huf_per_unit        as aum_huf,
  ret.ytd, ret.r_1y, ret.r_3y_ann, ret.r_6m_ann,
  v.vol_1y,
  fl.turnover_cum_30d, fl.turnover_avg_30d, fl.turnover_cum_1y, fl.turnover_avg_1y,
  fl.turnover_cum_30d * fx.huf_per_unit  as turnover_cum_30d_huf,
  fl.turnover_cum_1y  * fx.huf_per_unit  as turnover_cum_1y_huf,
  tw.turnover_3m  * fx.huf_per_unit      as turnover_cum_3m_huf,
  tw.turnover_ytd * fx.huf_per_unit      as turnover_cum_ytd_huf,
  ra.rf_rate, ra.sharpe_1y, ra.sortino_1y,
  dr.max_drawdown, dr.peak_date, dr.trough_date,
  dr.decline_days, dr.recovery_date, dr.recovery_days,
  t.ak_dij, t.ter, t.ter_year,
  liq.is_illiquid, liq.status, liq.days_stale,
  pg.group_isin as peer_group_isin, pg.group_name as peer_group_name
from fund_dim d
join last_date ld using (fund_id)
left join fund_nav          n   on n.fund_id=d.fund_id  and n.obs_date=ld.d
left join fund_returns_daily ret on ret.fund_id=d.fund_id and ret.obs_date=ld.d
left join fund_vol_daily    v   on v.fund_id=d.fund_id  and v.obs_date=ld.d
left join fund_flows_daily  fl  on fl.fund_id=d.fund_id and fl.obs_date=ld.d
left join fund_ratios_daily ra  on ra.fund_id=d.fund_id and ra.obs_date=ld.d
left join fund_drawdown     dr  on dr.fund_id=d.fund_id
left join lateral (
  select ak_dij, ter, ter_year from fund_ter
  where fund_id=d.fund_id order by ter_year desc limit 1
) t on true
left join fund_liquidity    liq on liq.fund_id=d.fund_id
left join lateral (
  select huf_per_unit from fx_rate
  where currency=d.currency and obs_date <= ld.d
  order by obs_date desc limit 1
) fx on true
left join lateral (
  select
    sum(turnover) filter (where obs_date >= ld.d - interval '3 months') as turnover_3m,
    sum(turnover) filter (where obs_date >= date_trunc('year', ld.d))    as turnover_ytd
  from fund_nav
  where fund_id = d.fund_id and turnover is not null and obs_date <= ld.d
) tw on true
left join fund_peer_group pg on pg.fund_id=d.fund_id;

alter table fund_latest add primary key (fund_id);
create index idx_fl_category on fund_latest (category);
create index idx_fl_manager  on fund_latest (manager);
create index idx_fl_currency on fund_latest (currency);
grant select on fund_latest to anon, authenticated;

-- ---------------------------------------------------------------------
-- B) v_fund_full  (+ series)
-- ---------------------------------------------------------------------
drop view if exists v_fund_full;
create view v_fund_full
with (security_invoker = true) as
select
  d.fund_id, d.isin, d.name, d.series, d.manager, d.category, d.currency, d.risk_return,
  n.obs_date, n.price, n.nav, n.turnover,
  ret.ytd, ret.r_1y, ret.r_3y_ann, ret.r_6m_ann,
  v.vol_1y,
  fl.turnover_cum_30d, fl.turnover_avg_30d, fl.turnover_cum_1y, fl.turnover_avg_1y,
  ra.rf_rate, ra.sharpe_1y, ra.sortino_1y,
  liq.is_illiquid, liq.status
from fund_nav n
join      fund_dim          d   using (fund_id)
left join fund_returns_daily ret using (fund_id, obs_date)
left join fund_vol_daily    v   using (fund_id, obs_date)
left join fund_flows_daily  fl  using (fund_id, obs_date)
left join fund_ratios_daily ra  using (fund_id, obs_date)
left join fund_liquidity    liq using (fund_id);

grant select on v_fund_full to anon, authenticated;

-- >>>>>>>>>>>>>>>>>> market_aum_table.sql <<<<<<<<<<<<<<<<<<

-- Napi teljes piaci AUM és nettó forgalom kategóriánként, forintra váltva — ELŐSZÁMÍTOTT TÁBLA.
-- A HUF-alapoknál nincs devizaváltó-keresés (rate=1), csak a nem-HUF alapoknál as-of árfolyam → gyors.
drop view  if exists v_market_aum_daily;
drop table if exists market_aum_daily;

create table market_aum_daily as
select x.obs_date, x.category,
       round(sum(x.nav      * x.rate)::numeric, 0) as aum_huf,
       round(sum(x.turnover * x.rate)::numeric, 0) as turnover_huf
from (
  select n.obs_date, d.category,
         coalesce(n.nav,0)      as nav,
         coalesce(n.turnover,0) as turnover,
         case when d.currency = 'HUF' then 1
              else coalesce((
                     select f.huf_per_unit from fx_rate f
                     where f.currency = d.currency and f.obs_date <= n.obs_date
                     order by f.obs_date desc limit 1), 1)
         end as rate
  from fund_nav n
  join fund_dim d on d.fund_id = n.fund_id
  where n.nav is not null
) x
group by x.obs_date, x.category;

create index if not exists ix_market_aum_date on market_aum_daily(obs_date);
grant select on market_aum_daily to anon, authenticated;
