create or replace function public.add_material_category_payload(
  p_payload jsonb
)
returns table (
  category text,
  inserted_count integer
)
language plpgsql
security definer
set search_path = public
as $$
declare
  v_category text := btrim(coalesce(p_payload ->> 'category', ''));
  v_no_model boolean := coalesce((p_payload ->> 'no_model')::boolean, false);
  v_item jsonb;
  v_material_code text;
  v_model text;
  v_language text;
  v_quantity integer;
  v_unit_price numeric;
  v_inserted integer := 0;
begin
  if v_category = '' then
    raise exception '物料品类不能为空';
  end if;

  if jsonb_typeof(p_payload -> 'items') <> 'array'
     or jsonb_array_length(p_payload -> 'items') = 0 then
    raise exception '库存行不能为空';
  end if;

  update public.material_categories as mc
     set no_model = v_no_model
   where mc.category = v_category;

  if not found then
    insert into public.material_categories (category, no_model)
    values (v_category, v_no_model);
  end if;

  for v_item in
    select value from jsonb_array_elements(p_payload -> 'items')
  loop
    v_material_code := btrim(coalesce(v_item ->> 'material_code', ''));
    v_model := coalesce(nullif(btrim(coalesce(v_item ->> 'model', '')), ''), '无需型号');
    v_language := btrim(coalesce(v_item ->> 'language', ''));
    v_quantity := case
      when nullif(v_item ->> 'quantity', '') is null then 0
      else (v_item ->> 'quantity')::integer
    end;
    v_unit_price := case
      when nullif(v_item ->> 'unit_price', '') is null then 0
      else (v_item ->> 'unit_price')::numeric
    end;

    if v_material_code = '' then
      raise exception '物料编码不能为空';
    end if;
    if v_language = '' then
      raise exception '语种不能为空';
    end if;

    if not exists (
      select 1
        from public.inventory_items as ii
       where ii.category = v_category
         and ii.model = v_model
         and ii.language = v_language
    ) then
      insert into public.inventory_items (
        material_code,
        category,
        model,
        language,
        quantity,
        unit_price,
        updated_at
      )
      values (
        v_material_code,
        v_category,
        v_model,
        v_language,
        v_quantity,
        v_unit_price,
        now()
      );
      v_inserted := v_inserted + 1;
    end if;
  end loop;

  return query
  select v_category, v_inserted;
end;
$$;

revoke all on function public.add_material_category_payload(jsonb) from public;
grant execute on function public.add_material_category_payload(jsonb) to service_role;

grant select, insert, update, delete on table
  public.material_categories,
  public.inventory_items,
  public.inventory_transactions
to service_role;

grant usage, select on all sequences in schema public to service_role;
