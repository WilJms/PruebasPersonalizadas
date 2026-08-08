import { type KeyboardEvent, type ReactNode, useId, useRef } from "react";

export interface RovingTab<Key extends string> {
  key: Key;
  label: ReactNode;
  panel: ReactNode;
}

export function RovingTabs<Key extends string>({
  label,
  tabs,
  value,
  onChange,
}: {
  label: string;
  tabs: Array<RovingTab<Key>>;
  value: Key;
  onChange: (value: Key) => void;
}) {
  const baseId = useId();
  const refs = useRef<Array<HTMLButtonElement | null>>([]);
  const activeIndex = Math.max(0, tabs.findIndex((tab) => tab.key === value));

  const selectFromKeyboard = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    let nextIndex: number | null = null;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      nextIndex = (index + 1) % tabs.length;
    } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      nextIndex = (index - 1 + tabs.length) % tabs.length;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = tabs.length - 1;
    }
    if (nextIndex === null) return;
    event.preventDefault();
    onChange(tabs[nextIndex].key);
    refs.current[nextIndex]?.focus();
  };

  return (
    <>
      <div className="tab-list" role="tablist" aria-label={label}>
        {tabs.map((tab, index) => (
          <button
            aria-controls={`${baseId}-${tab.key}-panel`}
            aria-selected={index === activeIndex}
            className={index === activeIndex ? "active" : ""}
            id={`${baseId}-${tab.key}-tab`}
            key={tab.key}
            onClick={() => onChange(tab.key)}
            onKeyDown={(event) => selectFromKeyboard(event, index)}
            ref={(element) => {
              refs.current[index] = element;
            }}
            role="tab"
            tabIndex={index === activeIndex ? 0 : -1}
            type="button"
          >
            {tab.label}
          </button>
        ))}
      </div>
      {tabs.map((tab, index) => (
        <section
          aria-labelledby={`${baseId}-${tab.key}-tab`}
          hidden={index !== activeIndex}
          id={`${baseId}-${tab.key}-panel`}
          key={tab.key}
          role="tabpanel"
          tabIndex={0}
        >
          {tab.panel}
        </section>
      ))}
    </>
  );
}
