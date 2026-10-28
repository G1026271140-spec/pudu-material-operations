import { Fragment } from 'react';
import type { ReactNode } from 'react';
import { groupByCategory } from './categoryGroups';
import type { CategoryGroup } from './categoryGroups';
import './category-groups.css';

type Props<T> = { items: readonly T[]; category: (item: T) => string; lang: 'zh' | 'en'; render: (item: T, index: number, displayIndex: number) => ReactNode; quantity?: (item: T) => number; actions?: (group: CategoryGroup<T>) => ReactNode };
function description<T>(group: CategoryGroup<T>, lang: 'zh' | 'en') { return lang === 'zh' ? `${group.entries.length} 条 · ${group.quantity} 件` : `${group.entries.length} lines · ${group.quantity} items`; }

export function CategoryRows<T>({ items, category, columns, lang, render, quantity, actions }: Props<T> & { columns: number }) {
  let position = 0;
  return <>{groupByCategory(items, category, quantity).map(group => <Fragment key={group.category}>
    <tr className="request-category-row"><td className="request-category-band" colSpan={columns} role="rowheader"><div><strong>{group.category || (lang === 'zh' ? '未分类' : 'Uncategorized')}</strong><span>{description(group, lang)}</span>{actions?.(group)}</div></td></tr>
    {group.entries.map(({ item, index }) => render(item, index, position++))}
  </Fragment>)}</>;
}

export function CategoryList<T>({ items, category, lang, render, quantity, actions }: Props<T>) {
  let position = 0;
  return <>{groupByCategory(items, category, quantity).map(group => <section className="request-category-group" key={group.category}>
    <div className="request-category-label"><strong>{group.category || (lang === 'zh' ? '未分类' : 'Uncategorized')}</strong><span>{description(group, lang)}</span>{actions?.(group)}</div>
    <div className="request-category-items">{group.entries.map(({ item, index }) => render(item, index, position++))}</div>
  </section>)}</>;
}
