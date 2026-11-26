import { useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { Icon } from '../Icon'

export type TableColumn<Row> = {
  id: string; label: string; value: (row: Row) => string | number; render?: (row: Row) => ReactNode
}

export function DataTable<Row>({ rows, columns, searchText, searchPlaceholder = 'Filter records…', onSelect, emptyTitle = 'No records found', pageSize = 5 }: {
  rows: Row[]; columns: TableColumn<Row>[]; searchText: (row: Row) => string; searchPlaceholder?: string
  onSelect?: (row: Row) => void; emptyTitle?: string; pageSize?: number
}) {
  const [filter, setFilter] = useState('')
  const [sortBy, setSortBy] = useState('')
  const [direction, setDirection] = useState<'asc' | 'desc'>('asc')
  const [page, setPage] = useState(0)
  const filtered = useMemo(() => rows.filter(row => searchText(row).toLowerCase().includes(filter.trim().toLowerCase())), [rows, searchText, filter])
  const sorted = useMemo(() => {
    if (!sortBy) return filtered
    const column = columns.find(item => item.id === sortBy)
    if (!column) return filtered
    return [...filtered].sort((a, b) => {
      const left = column.value(a); const right = column.value(b)
      const comparison = typeof left === 'number' && typeof right === 'number' ? left - right : String(left).localeCompare(String(right))
      return direction === 'asc' ? comparison : -comparison
    })
  }, [filtered, columns, sortBy, direction])
  const pageCount = Math.max(1, Math.ceil(sorted.length / pageSize))
  const visibleRows = sorted.slice(page * pageSize, (page + 1) * pageSize)

  function chooseSort(id: string) {
    if (sortBy === id) setDirection(value => value === 'asc' ? 'desc' : 'asc')
    else { setSortBy(id); setDirection('asc') }
    setPage(0)
  }

  function exportCsv() {
    const escape = (value: string | number) => `"${String(value).replaceAll('"', '""')}"`
    const lines = [columns.map(column => escape(column.label)).join(','), ...sorted.map(row => columns.map(column => escape(column.value(row))).join(','))]
    const url = URL.createObjectURL(new Blob([lines.join('\r\n')], { type: 'text/csv;charset=utf-8' }))
    const link = document.createElement('a')
    link.href = url; link.download = 'privacyguard-demo-export.csv'; link.click(); URL.revokeObjectURL(url)
  }

  return <div className="data-table-component">
    <div className="table-toolbar"><label className="table-search"><Icon name="search" size={15} /><input aria-label="Filter table" placeholder={searchPlaceholder} value={filter} onChange={event => { setFilter(event.target.value); setPage(0) }} /></label><span className="table-result-count">{filtered.length} {filtered.length === 1 ? 'record' : 'records'}</span><button className="table-export" onClick={exportCsv} disabled={sorted.length === 0} title="Export currently filtered rows to CSV"><Icon name="download" size={14} /> Export CSV</button></div>
    {visibleRows.length ? <div className="table-wrap data-table-wrap"><table><thead><tr>{columns.map(column => <th key={column.id}><button className={`sort-heading ${sortBy === column.id ? 'sorted' : ''}`} onClick={() => chooseSort(column.id)}>{column.label}<span>{sortBy === column.id ? direction === 'asc' ? '↑' : '↓' : '↕'}</span></button></th>)}</tr></thead><tbody>{visibleRows.map((row, index) => <tr key={columns[0]?.value(row) as string | number ?? index} onClick={() => onSelect?.(row)} onKeyDown={event => { if (onSelect && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); onSelect(row) } }} tabIndex={onSelect ? 0 : undefined} className={onSelect ? 'clickable-row' : undefined}>{columns.map(column => <td key={column.id}>{column.render ? column.render(row) : column.value(row)}</td>)}</tr>)}</tbody></table></div> : <div className="table-empty"><span className="empty-icon"><Icon name="search" size={17} /></span><b>{emptyTitle}</b><p>Try changing the search text or filters.</p></div>}
    <div className="table-pagination"><span>Page {Math.min(page + 1, pageCount)} of {pageCount}</span><div><button onClick={() => setPage(value => Math.max(0, value - 1))} disabled={page === 0}>Previous</button><button onClick={() => setPage(value => Math.min(pageCount - 1, value + 1))} disabled={page >= pageCount - 1}>Next</button></div></div>
  </div>
}
