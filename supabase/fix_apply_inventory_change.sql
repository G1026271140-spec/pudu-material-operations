alter table public.inventory_items
  drop constraint if exists inventory_items_quantity_check;

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
