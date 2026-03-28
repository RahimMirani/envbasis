interface Command {
  cmd: string;
  args: string;
}

interface CodeBlockProps {
  commands: Command[];
}

export default function CodeBlock({ commands }: CodeBlockProps) {
  return (
    <pre className="code-block">
      {commands.map((line, idx) => (
        <code key={idx}>
          <span className="code-cmd">{line.cmd}</span>{' '}
          <span className="code-args">{line.args}</span>
          {'\n'}
        </code>
      ))}
    </pre>
  );
}
