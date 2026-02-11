import { CheckCircle, XCircle, AlertTriangle, ChevronDown, ChevronUp, Cpu, RefreshCw } from 'lucide-react'
import { useState } from 'react'
import { Chip } from '../common'
import type { ValidationResult } from '../../types/api'

interface ValidationStatusProps {
  validation?: ValidationResult
  attempts?: number
  providerUsed?: string
  modelUsed?: string
  isValidating?: boolean
}

export function ValidationStatus({
  validation,
  attempts = 1,
  providerUsed,
  modelUsed,
  isValidating = false
}: ValidationStatusProps) {
  const [expanded, setExpanded] = useState(false)

  if (isValidating) {
    return (
      <div className="flex items-center gap-2">
        <div className="w-4 h-4 border-2 border-primary-500 border-t-transparent rounded-full animate-spin" />
        <span className="text-sm text-[var(--text-secondary)]">Validating...</span>
      </div>
    )
  }

  if (!validation) {
    return null
  }

  const { yamlOk, yamlError, actionlintOk, actionlintOutput } = validation

  const getYamlStatus = () => {
    if (yamlOk) {
      return { variant: 'success' as const, icon: CheckCircle, text: 'YAML Valid' }
    }
    return { variant: 'danger' as const, icon: XCircle, text: 'YAML Invalid' }
  }

  const getActionlintStatus = () => {
    if (actionlintOk) {
      return { variant: 'success' as const, icon: CheckCircle, text: 'Lint Passed' }
    }
    // Check if it's just warnings
    if (actionlintOutput?.includes(':info:') && !actionlintOutput?.includes(':error:')) {
      return { variant: 'warning' as const, icon: AlertTriangle, text: 'Lint Warnings' }
    }
    return { variant: 'danger' as const, icon: XCircle, text: 'Lint Failed' }
  }

  const yamlStatus = getYamlStatus()
  const lintStatus = getActionlintStatus()
  const YamlIcon = yamlStatus.icon
  const LintIcon = lintStatus.icon

  const hasDetails = yamlError || actionlintOutput

  return (
    <div className="space-y-2">
      {/* Status chips */}
      <div className="flex flex-wrap items-center gap-2">
        <Chip variant={yamlStatus.variant} icon={<YamlIcon className="w-3.5 h-3.5" />}>
          {yamlStatus.text}
        </Chip>

        <Chip variant={lintStatus.variant} icon={<LintIcon className="w-3.5 h-3.5" />}>
          {lintStatus.text}
        </Chip>

        {/* Always show attempts count */}
        <Chip variant="info" icon={<RefreshCw className="w-3.5 h-3.5" />}>
          {attempts === 1 ? '1 attempt' : `${attempts} attempts`}
        </Chip>

        {/* Show LLM provider/model */}
        {providerUsed && modelUsed && (
          <Chip variant="neutral" icon={<Cpu className="w-3.5 h-3.5" />}>
            {providerUsed}: {modelUsed}
          </Chip>
        )}

        {hasDetails && (
          <button
            onClick={() => setExpanded(!expanded)}
            className="inline-flex items-center gap-1 px-2 py-1 text-xs text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
          >
            {expanded ? (
              <>
                Hide details <ChevronUp className="w-3 h-3" />
              </>
            ) : (
              <>
                Show details <ChevronDown className="w-3 h-3" />
              </>
            )}
          </button>
        )}
      </div>

      {/* Expanded details */}
      {expanded && hasDetails && (
        <div className="p-3 rounded-lg bg-[var(--bg-glass)] border border-[var(--border)] text-sm font-mono overflow-x-auto">
          {yamlError && (
            <div className="mb-3">
              <p className="text-xs font-sans font-medium text-red-500 mb-1">YAML Error:</p>
              <pre className="text-xs text-red-400 whitespace-pre-wrap">{yamlError}</pre>
            </div>
          )}
          {actionlintOutput && (
            <div>
              <p className="text-xs font-sans font-medium text-[var(--text-secondary)] mb-1">
                actionlint Output:
              </p>
              <pre className="text-xs text-[var(--text-muted)] whitespace-pre-wrap">
                {actionlintOutput}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
