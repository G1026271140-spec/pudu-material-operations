create table if not exists public.material_categories (
  id bigserial primary key,
  category text not null unique,
  no_model boolean not null default false,
  created_at timestamptz not null default now()
);

create table if not exists public.inventory_items (
  id bigserial primary key,
  material_code text not null unique,
  category text not null,
  model text not null default '无需型号',
  language text not null,
  quantity integer not null default 0 check (quantity >= 0),
  unit_price numeric not null default 0,
  updated_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  unique (category, model, language)
);

create table if not exists public.inventory_transactions (
  id bigserial primary key,
  created_at timestamptz not null default now(),
  action text not null,
  category text not null,
  model text not null default '无需型号',
  language text not null,
  quantity integer not null,
  before_quantity integer not null,
  after_quantity integer not null,
  note text default ''
);

create index if not exists idx_inventory_items_category
  on public.inventory_items (category);

create index if not exists idx_inventory_items_model
  on public.inventory_items (model);

create index if not exists idx_inventory_items_language
  on public.inventory_items (language);

create index if not exists idx_inventory_transactions_created_at
  on public.inventory_transactions (created_at desc);

create or replace function public.apply_inventory_change(
  p_action text,
  p_category text,
  p_model text,
  p_language text,
  p_quantity integer,
  p_note text default ''
)
returns table (
  created_at timestamptz,
  action text,
  category text,
  model text,
  language text,
  quantity integer,
  before_quantity integer,
  after_quantity integer,
  note text
)
language plpgsql
security definer
set search_path = public
as $$
declare
  v_item public.inventory_items%rowtype;
  v_before integer;
  v_after integer;
  v_created_at timestamptz;
begin
  if p_quantity < 0 then
    raise exception '数量不能小于 0';
  end if;

  select *
    into v_item
    from public.inventory_items
   where category = p_category
     and model = coalesce(nullif(p_model, ''), '无需型号')
     and language = p_language
   for update;

  if not found then
    raise exception '未找到物料组合: % / % / %', p_category, p_model, p_language;
  end if;

  v_before := v_item.quantity;

  if p_action = '入库增加' then
    v_after := v_before + p_quantity;
  elsif p_action = '出库减少' then
    v_after := v_before - p_quantity;
    if v_after < 0 then
      raise exception '库存不足: 当前 %, 出库 %', v_before, p_quantity;
    end if;
  elsif p_action = '盘点设为' then
    v_after := p_quantity;
  else
    raise exception '不支持的操作: %', p_action;
  end if;

  update public.inventory_items
     set quantity = v_after,
         updated_at = now()
   where id = v_item.id;

  insert into public.inventory_transactions (
    action,
    category,
    model,
    language,
    quantity,
    before_quantity,
    after_quantity,
    note
  )
  values (
    p_action,
    p_category,
    coalesce(nullif(p_model, ''), '无需型号'),
    p_language,
    p_quantity,
    v_before,
    v_after,
    coalesce(p_note, '')
  )
  returning public.inventory_transactions.created_at
    into v_created_at;

  return query
  select
    v_created_at,
    p_action,
    p_category,
    coalesce(nullif(p_model, ''), '无需型号'),
    p_language,
    p_quantity,
    v_before,
    v_after,
    coalesce(p_note, '');
end;
$$;
