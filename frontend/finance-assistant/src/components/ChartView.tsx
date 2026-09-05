import { useEffect, useRef } from 'react'
import {
  ArcElement,
  BarController,
  BarElement,
  CategoryScale,
  Chart,
  DoughnutController,
  Filler,
  Legend,
  LinearScale,
  LineController,
  LineElement,
  PieController,
  PointElement,
  Title,
  Tooltip,
} from 'chart.js'
import ChartDataLabels from 'chartjs-plugin-datalabels'
import type { ChartData, ChartSeries } from '../lib/types'

Chart.register(
  BarController,
  LineController,
  PieController,
  DoughnutController,
  BarElement,
  LineElement,
  PointElement,
  ArcElement,
  CategoryScale,
  LinearScale,
  Tooltip,
  Legend,
  Filler,
  Title,
  ChartDataLabels,
)

// Palette drawn from the app's design tokens
const SERIES_PALETTE = [
  '#0f6b52', // accent
  '#34c79e', // accent-dark
  '#9a6b12', // amber
  '#a23b3b', // brick
  '#6366f1', // indigo
  '#8b5cf6', // violet
  '#ec4899', // pink
]

function withAlpha(hex: string, alpha: number): string {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

function chartJsType(kind: string): string {
  if (kind === 'area') return 'line'
  if (kind === 'doughnut') return 'doughnut'
  if (kind === 'pie') return 'pie'
  if (kind === 'line') return 'line'
  if (kind === 'combo') return 'bar' // base type for combo
  return 'bar'
}

function formatCompact(value: number): string {
  if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`
  if (value >= 1_000) return `$${(value / 1_000).toFixed(1)}K`
  return `$${value.toFixed(0)}`
}

function buildDataset(series: ChartSeries, index: number, baseKind: string, dark?: boolean) {
  const seriesKind = series.kind ?? (baseKind === 'combo' ? 'bar' : baseKind)
  const color = SERIES_PALETTE[index % SERIES_PALETTE.length]
  const isArea = seriesKind === 'area'
  const isLineLike = seriesKind === 'line' || isArea
  const isDashed = series.style === 'dashed'

  return {
    type: chartJsType(seriesKind) as any,
    label: series.name,
    data: series.data,
    yAxisID: series.axis === 'right' ? 'y1' : 'y',
    backgroundColor: isLineLike
      ? withAlpha(color, isArea ? 0.15 : 0)
      : withAlpha(color, 0.8),
    borderColor: color,
    borderWidth: isLineLike ? 2.5 : 0,
    borderDash: isDashed ? [6, 4] : [],
    borderRadius: seriesKind === 'bar' ? 6 : 0,
    fill: isArea,
    tension: isLineLike ? 0.35 : 0,
    pointRadius: isLineLike ? 3 : 0,
    pointHoverRadius: isLineLike ? 5 : 0,
    pointBackgroundColor: color,
    pointBorderColor: dark ? '#0d0f11' : '#ffffff',
    pointBorderWidth: 2,
    order: isLineLike ? 0 : 1, // lines render on top of bars
  }
}

export function ChartView({ chart, dark, compact }: { chart: ChartData; dark?: boolean; compact?: boolean }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const textColor = dark ? '#edefef' : '#12141a'
    const mutedColor = dark ? '#6b7278' : '#8b9096'
    const gridColor = dark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.06)'
    const isPie = chart.kind === 'pie' || chart.kind === 'doughnut'

    let instance: Chart | undefined
    let config: any

    if (isPie) {
      config = {
        type: chartJsType(chart.kind),
        data: {
          labels: chart.labels,
          datasets: [
            {
              label: chart.series[0]?.name ?? '',
              data: chart.series[0]?.data ?? [],
              backgroundColor: chart.labels.map((_, i) =>
                withAlpha(SERIES_PALETTE[i % SERIES_PALETTE.length], 0.85),
              ),
              borderColor: dark ? '#0d0f11' : '#ffffff',
              borderWidth: 2,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          animation: { duration: 1000, easing: 'easeOutQuart' },
          layout: { padding: { bottom: 4 } },
          plugins: {
            legend: {
              position: 'bottom' as const,
              labels: {
                color: textColor,
                padding: 10,
                usePointStyle: true,
                pointStyleWidth: 8,
                boxWidth: 8,
                font: { family: '"Outfit", sans-serif', size: compact ? 9 : 11 },
              },
            },
            tooltip: { enabled: true },
            datalabels: { display: false },
          },
        },
      }
    } else {
      // Bar, Line, Area, Combo — all go through the same path
      const datasets = chart.series.map((s, i) => buildDataset(s, i, chart.kind, dark))
      const hasRightAxis = chart.series.some((s) => s.axis === 'right')

      const valueAxis = (title?: string) => ({
        beginAtZero: true,
        title: { display: Boolean(title), text: title ?? '', color: mutedColor, font: { family: '"Outfit", sans-serif', size: 11 } },
        ticks: { color: mutedColor, callback: (v: number) => formatCompact(v), font: { family: '"JetBrains Mono", monospace', size: compact ? 9 : 11 } },
        grid: { color: gridColor },
      })

      const scales: any = {
        x: {
          title: { display: Boolean(chart.xLabel), text: chart.xLabel ?? '', color: mutedColor, font: { family: '"Outfit", sans-serif', size: 11 } },
          ticks: {
            color: mutedColor,
            font: { family: '"Outfit", sans-serif', size: compact ? 8 : 11 },
            maxRotation: compact ? 45 : 35,
            callback: function(this: any, _val: any, index: number) {
              const label = chart.labels[index] ?? ''
              return compact && label.length > 12 ? label.slice(0, 11) + '…' : label.length > 18 ? label.slice(0, 17) + '…' : label
            },
          },
          grid: { color: gridColor },
        },
        y: valueAxis(chart.yLabel),
      }

      if (hasRightAxis) {
        scales.y1 = {
          ...valueAxis(chart.y2Label),
          position: 'right',
          grid: { drawOnChartArea: false, color: gridColor },
        }
      }

      const multiSeries = chart.series.length > 1

      config = {
        type: chartJsType(chart.kind),
        data: { labels: chart.labels, datasets },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          animation: { duration: 1000, easing: 'easeOutQuart' },
          interaction: { mode: 'index' as const, intersect: false },
          scales,
          plugins: {
            legend: {
              display: multiSeries,
              position: 'bottom' as const,
              labels: {
                color: textColor,
                usePointStyle: true,
                pointStyleWidth: 10,
                padding: 12,
                font: { family: '"Outfit", sans-serif', size: compact ? 10 : 11 },
              },
            },
            tooltip: {
              enabled: true,
              backgroundColor: dark ? '#1b1f23' : '#ffffff',
              titleColor: textColor,
              bodyColor: mutedColor,
              borderColor: dark ? '#262b2f' : '#dee2df',
              borderWidth: 1,
              padding: 10,
              cornerRadius: 8,
              titleFont: { family: '"Outfit", sans-serif', weight: '600' as const },
              bodyFont: { family: '"JetBrains Mono", monospace', size: 12 },
              callbacks: {
                label: (ctx: any) => ` ${ctx.dataset.label}: ${formatCompact(ctx.parsed.y)}`,
              },
            },
            datalabels: {
              display: compact ? false : 'auto',
              align: 'top' as const,
              anchor: 'end' as const,
              color: textColor,
              formatter: (value: number) => formatCompact(value),
              font: { weight: 600 as const, size: compact ? 9 : 11, family: '"JetBrains Mono", monospace' },
            },
          },
        },
      }
    }

    let initTimeout: number

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && !instance) {
          // Add a tiny delay to ensure flex layout is fully settled when scrolled into view
          initTimeout = window.setTimeout(() => {
            instance = new Chart(canvas, config)
          }, 50)
          observer.disconnect()
        }
      },
      { threshold: 0.1 }
    )

    observer.observe(canvas)

    return () => {
      observer.disconnect()
      clearTimeout(initTimeout)
      instance?.destroy()
    }
  }, [chart, dark, compact])

  const isPie = chart.kind === 'pie' || chart.kind === 'doughnut'
  const isCombo = chart.kind === 'combo'
  const height = compact
    ? (isPie ? 'h-56' : isCombo ? 'h-52' : 'h-44')
    : (isPie ? 'h-80' : isCombo ? 'h-72' : 'h-64')

  return (
    <div className={`chart-fade-in ${height} w-full`}>
      <canvas ref={canvasRef} />
    </div>
  )
}
