alter table public.inventory_items
  drop constraint if exists inventory_items_quantity_check;

alter table public.inventory_transactions
  add column if not exists reversed_at timestamptz;

alter table public.inventory_transactions
  add column if not exists reversal_of bigint references public.inventory_transactions(id);

create index if not exists idx_inventory_transactions_reversal_of
  on public.inventory_transactions (reversal_of);

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
  if p_action <> '盘点设为' and p_quantity < 0 then
    raise exception '领取和采购数量不能小于 0';
  end if;

  select ii.*
    into v_item
    from public.inventory_items as ii
   where ii.category = p_category
     and ii.model = coalesce(nullif(p_model, ''), '无需型号')
     and ii.language = p_language
   for update;

  if not found then
    raise exception '未找到物料组合: % / % / %', p_category, p_model, p_language;
  end if;

  v_before := v_item.quantity;

  if p_action in ('物料采购（增加库存）', '入库增加') then
    v_after := v_before + p_quantity;
  elsif p_action in ('物料领取（减少库存）', '出库减少') then
    v_after := v_before - p_quantity;
  elsif p_action = '盘点设为' then
    v_after := p_quantity;
  else
    raise exception '不支持的操作: %', p_action;
  end if;

  update public.inventory_items as ii
     set quantity = v_after,
         updated_at = now()
   where ii.id = v_item.id;

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

revoke all on function public.apply_inventory_change(text, text, text, text, integer, text) from public;
grant execute on function public.apply_inventory_change(text, text, text, text, integer, text) to service_role;

create or replace function public.revert_inventory_transaction(
  p_transaction_id bigint,
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
  v_tx public.inventory_transactions%rowtype;
  v_item public.inventory_items%rowtype;
  v_before integer;
  v_after integer;
  v_delta integer;
  v_created_at timestamptz;
  v_note text;
begin
  select itx.*
    into v_tx
    from public.inventory_transactions as itx
   where itx.id = p_transaction_id
   for update;

  if not found then
    raise exception '未找到库存提交记录: %', p_transaction_id;
  end if;

  if v_tx.reversed_at is not null then
    raise exception '该库存提交记录已经撤回: %', p_transaction_id;
  end if;

  if v_tx.reversal_of is not null then
    raise exception '撤回记录不能再次撤回: %', p_transaction_id;
  end if;

  select ii.*
    into v_item
    from public.inventory_items as ii
   where ii.category = v_tx.category
     and ii.model = v_tx.model
     and ii.language = v_tx.language
   for update;

  if not found then
    raise exception '未找到原库存组合: % / % / %', v_tx.category, v_tx.model, v_tx.language;
  end if;

  v_before := v_item.quantity;
  v_delta := v_tx.after_quantity - v_tx.before_quantity;
  v_after := v_before - v_delta;
  v_note := trim(coalesce(p_note, ''));
  if v_note = '' then
    v_note := '撤回记录ID: ' || p_transaction_id;
  else
    v_note := v_note || '（撤回记录ID: ' || p_transaction_id || '）';
  end if;

  update public.inventory_items as ii
     set quantity = v_after,
         updated_at = now()
   where ii.id = v_item.id;

  update public.inventory_transactions as itx
     set reversed_at = now()
   where itx.id = v_tx.id;

  insert into public.inventory_transactions (
    action,
    category,
    model,
    language,
    quantity,
    before_quantity,
    after_quantity,
    note,
    reversal_of
  )
  values (
    '撤回',
    v_tx.category,
    v_tx.model,
    v_tx.language,
    abs(v_delta),
    v_before,
    v_after,
    v_note,
    v_tx.id
  )
  returning public.inventory_transactions.created_at
    into v_created_at;

  return query
  select
    v_created_at,
    '撤回'::text,
    v_tx.category,
    v_tx.model,
    v_tx.language,
    abs(v_delta),
    v_before,
    v_after,
    v_note;
end;
$$;

revoke all on function public.revert_inventory_transaction(bigint, text) from public;
grant execute on function public.revert_inventory_transaction(bigint, text) to service_role;

create or replace function public.replace_inventory_transaction(
  p_transaction_id bigint,
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
  v_note text;
begin
  perform 1
    from public.revert_inventory_transaction(
      p_transaction_id,
      '修改前自动撤回'
    );

  v_note := trim(coalesce(p_note, ''));
  if v_note = '' then
    v_note := '修正记录，原记录ID: ' || p_transaction_id;
  else
    v_note := v_note || '（修正原记录ID: ' || p_transaction_id || '）';
  end if;

  return query
  select *
    from public.apply_inventory_change(
      p_action,
      p_category,
      coalesce(nullif(p_model, ''), '无需型号'),
      p_language,
      p_quantity,
      v_note
    );
end;
$$;

revoke all on function public.replace_inventory_transaction(bigint, text, text, text, text, integer, text) from public;
grant execute on function public.replace_inventory_transaction(bigint, text, text, text, text, integer, text) to service_role;
