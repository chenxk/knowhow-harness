import { useEffect, useState } from 'react'
import { fetchLab } from '../api/client'
import type { LabSpec, LabStatus } from '../api/types'

export function LabPanel({
  lab,
  refreshKey,
}: {
  lab: LabSpec
  refreshKey: string
}) {
  const [status, setStatus] = useState<LabStatus | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    setError('')
    fetchLab(lab.id)
      .then((next) => {
        if (!cancelled) setStatus(next)
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : '无法检查实验')
        }
      })
    return () => {
      cancelled = true
    }
  }, [lab.id, refreshKey])

  const checks = status?.checks ?? {}
  const steps = status?.lab.steps ?? lab.steps
  const passed = steps.filter((step) => checks[step.id]).length

  return (
    <section className="lab-panel">
      <header className="lab-head">
        <h3>{lab.title}</h3>
        <span className="lab-score">
          {passed}/{steps.length} 通过
        </span>
      </header>
      <ol className="lab-steps">
        {steps.map((step) => {
          const ok = checks[step.id] === true
          const known = step.id in checks
          return (
            <li key={step.id} className={ok ? 'pass' : known ? 'fail' : 'wait'}>
              <span className="lab-mark" aria-hidden>
                {ok ? '通过' : known ? '未过' : '…'}
              </span>
              <div>
                <p>{step.label}</p>
                {step.hint ? <p className="lab-hint">{step.hint}</p> : null}
              </div>
            </li>
          )
        })}
      </ol>
      {error ? <p className="lab-hint">{error}</p> : null}
    </section>
  )
}
