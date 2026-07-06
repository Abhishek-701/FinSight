const CHIPS = [
  { q: "What is NVIDIA's current stock price and latest reported revenue?", label: 'NVDA price + revenue' },
  { q: "Compare Apple's current market cap to its latest reported revenue.", label: 'AAPL market cap vs revenue' },
  { q: 'What cybersecurity risks did Walmart disclose?', label: 'WMT risk factors' },
  { q: "Compare JPMorgan's revenue to its current market cap.", label: 'JPM revenue vs cap' },
]

export default function ExampleChips({ disabled, onPick }: { disabled: boolean; onPick: (q: string) => void }) {
  return (
    <div className="chips">
      {CHIPS.map((chip) => (
        <button key={chip.label} className="chip" disabled={disabled} onClick={() => onPick(chip.q)}>
          {chip.label}
        </button>
      ))}
    </div>
  )
}
