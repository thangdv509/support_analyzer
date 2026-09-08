interface Props {
  text: string
  style?: React.CSSProperties
}

export default function MarkdownText({ text, style }: Props) {
  return (
    <div style={{ fontSize: 13, lineHeight: 1.7, ...style }}>
      {(text || '').split('\n').map((line, i) => {
        if (!line.trim()) return <div key={i} style={{ height: 6 }} />

        const isBullet = /^\s*[-•]\s/.test(line)
        const raw = isBullet ? line.replace(/^\s*[-•]\s*/, '') : line

        // Parse **bold** segments
        const parts = raw.split(/(\*\*[^*\n]+?\*\*)/)
        const rendered = parts.map((part, j) =>
          part.startsWith('**') && part.endsWith('**') ? (
            <strong key={j}>{part.slice(2, -2)}</strong>
          ) : (
            part
          ),
        )

        return (
          <div
            key={i}
            style={
              isBullet
                ? { display: 'flex', gap: 6, marginBottom: 3 }
                : { marginBottom: 2 }
            }
          >
            {isBullet && (
              <span style={{ color: '#888', flexShrink: 0, marginTop: 1 }}>•</span>
            )}
            <span>{rendered}</span>
          </div>
        )
      })}
    </div>
  )
}
