"use client";

import { KeyboardEvent, useEffect, useId, useMemo, useState } from "react";

type AutocompleteFieldProps = {
  label: string;
  value: string;
  options: readonly string[];
  onChange: (value: string) => void;
  onSelect?: (value: string) => void;
  placeholder?: string;
  loadOptions?: (query: string) => Promise<readonly string[]>;
  minimumQueryLength?: number;
  replaceOptionsWhenLoaded?: boolean;
};

export function AutocompleteField({
  label,
  value,
  options,
  onChange,
  onSelect,
  placeholder,
  loadOptions,
  minimumQueryLength = 1,
  replaceOptionsWhenLoaded = false
}: AutocompleteFieldProps) {
  const id = useId();
  const listId = `${id}-listbox`;
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const [searching, setSearching] = useState(false);
  const [remoteOptions, setRemoteOptions] = useState<readonly string[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open || !loadOptions) return;
    const lookupQuery = searching ? value.trim() : "";
    if (lookupQuery.length < minimumQueryLength) return;
    let active = true;
    const timer = window.setTimeout(async () => {
      setLoading(true);
      try {
        const loaded = await loadOptions(lookupQuery);
        if (active) setRemoteOptions(loaded);
      } catch {
        if (active) setRemoteOptions([]);
      } finally {
        if (active) setLoading(false);
      }
    }, 250);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [loadOptions, minimumQueryLength, open, searching, value]);

  const matches = useMemo(() => {
    const query = searching ? value.trim().toLocaleLowerCase("zh-CN") : "";
    const available = Array.from(new Set(
      replaceOptionsWhenLoaded && remoteOptions.length
        ? remoteOptions
        : [...remoteOptions, ...options]
    ));
    const filtered = query
      ? available.filter((option) => option.toLocaleLowerCase("zh-CN").includes(query))
      : available;
    return filtered.slice(0, 8);
  }, [options, remoteOptions, replaceOptionsWhenLoaded, searching, value]);

  function choose(option: string) {
    onChange(option);
    onSelect?.(option);
    setOpen(false);
    setSearching(false);
    setActiveIndex(0);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setOpen(true);
      setActiveIndex((current) => Math.min(current + 1, matches.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setOpen(true);
      setActiveIndex((current) => Math.max(current - 1, 0));
    } else if (event.key === "Enter" && open && matches[activeIndex]) {
      event.preventDefault();
      choose(matches[activeIndex]);
    } else if (event.key === "Escape") {
      setOpen(false);
    }
  }

  return (
    <div className="autocomplete-field">
      <label htmlFor={id}>{label}</label>
      <div className="autocomplete-control">
        <input
          id={id}
          role="combobox"
          aria-autocomplete="list"
          aria-controls={listId}
          aria-expanded={open}
          aria-activedescendant={open && matches[activeIndex] ? `${id}-option-${activeIndex}` : undefined}
          autoComplete="off"
          placeholder={placeholder}
          value={value}
          onChange={(event) => {
            onChange(event.target.value);
            setOpen(true);
            setSearching(true);
            setActiveIndex(0);
          }}
          onFocus={() => {
            setOpen(true);
            setSearching(false);
          }}
          onBlur={() => setOpen(false)}
          onKeyDown={handleKeyDown}
        />
        <button
          className="autocomplete-toggle"
          type="button"
          aria-label={`${open ? "收起" : "展开"}${label}选项`}
          tabIndex={-1}
          onMouseDown={(event) => event.preventDefault()}
          onClick={() => setOpen((current) => !current)}
        >
          <span aria-hidden="true" />
        </button>
        {open ? (
          <div className="autocomplete-menu" id={listId} role="listbox">
            {loading ? <p>正在查询百度地图...</p> : null}
            {matches.length ? matches.map((option, index) => (
              <button
                className={index === activeIndex ? "active" : ""}
                id={`${id}-option-${index}`}
                key={option}
                type="button"
                role="option"
                aria-selected={option === value}
                onMouseDown={(event) => event.preventDefault()}
                onMouseEnter={() => setActiveIndex(index)}
                onClick={() => choose(option)}
              >
                {option}
              </button>
            )) : !loading ? (
              <p>未找到预设项，将保留手动输入</p>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}
