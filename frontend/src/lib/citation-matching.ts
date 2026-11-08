type Point = { node: Text; offset: number };
type MappedCharacter = { start: Point; end: Point };

export type PassageMatch = {
  range: Range;
  text: string;
  fuzzy: boolean;
};

function isWordCharacter(value: string | undefined): boolean {
  return value !== undefined && /[\p{L}\p{N}]/u.test(value);
}

function readLayer(layer: HTMLElement): { text: string; points: Array<Point | null> } {
  const walker = document.createTreeWalker(layer, NodeFilter.SHOW_TEXT);
  let node = walker.nextNode();
  let text = "";
  const points: Array<Point | null> = [];
  let priorSpan: Element | null = null;

  while (node) {
    const textNode = node as Text;
    const currentSpan = textNode.parentElement?.closest("span") ?? null;
    const currentText = textNode.data;
    const previousCharacter = text[text.length - 1];
    const nextCharacter = currentText[0];
    if (
      text.length &&
      currentSpan !== priorSpan &&
      previousCharacter &&
      nextCharacter &&
      !/\s/.test(previousCharacter) &&
      !/\s/.test(nextCharacter)
    ) {
      text += " ";
      points.push(null);
    }
    for (let offset = 0; offset < currentText.length; offset += 1) {
      text += currentText[offset];
      points.push({ node: textNode, offset });
    }
    priorSpan = currentSpan;
    node = walker.nextNode();
  }
  return { text, points };
}

function normalize(
  text: string,
  points: Array<Point | null>,
): { text: string; characters: MappedCharacter[] } {
  let normalized = "";
  const characters: MappedCharacter[] = [];
  let previousPoint: Point | null = null;
  for (let index = 0; index < text.length; index += 1) {
    const current = text[index];
    if (
      current === "-" &&
      isWordCharacter(text[index - 1]) &&
      isWordCharacter(text.slice(index + 1).match(/^\s+([\p{L}\p{N}])/u)?.[1])
    ) {
      const gap = text.slice(index + 1).match(/^\s+/u)?.[0].length ?? 0;
      index += gap;
      continue;
    }
    if (/\s/.test(current)) {
      if (!normalized || normalized.endsWith(" ")) continue;
      normalized += " ";
      const point = points[index];
      if (point) characters.push({ start: point, end: { node: point.node, offset: point.offset + 1 } });
      if (point) previousPoint = point;
      continue;
    }
    const point = points[index];
    if (!point) {
      normalized += current.toLocaleLowerCase();
      if (!previousPoint) continue;
      const boundary = { node: previousPoint.node, offset: previousPoint.offset + 1 };
      characters.push({ start: boundary, end: boundary });
      continue;
    }
    const lowered = current.toLocaleLowerCase();
    normalized += lowered;
    for (let part = 0; part < lowered.length; part += 1) {
      characters.push({ start: point, end: { node: point.node, offset: point.offset + 1 } });
    }
    previousPoint = point;
  }
  return {
    text: normalized.trim(),
    characters: normalized.trim() === normalized ? characters : trimMap(normalized, characters),
  };
}

function trimMap(text: string, characters: MappedCharacter[]): MappedCharacter[] {
  let start = 0;
  let end = text.length;
  while (start < end && text[start] === " ") start += 1;
  while (end > start && text[end - 1] === " ") end -= 1;
  return characters.slice(start, end);
}

function makeRange(characters: MappedCharacter[], start: number, end: number): Range | null {
  const first = characters[start];
  const last = characters[end - 1];
  if (!first || !last) return null;
  const range = document.createRange();
  range.setStart(first.start.node, first.start.offset);
  range.setEnd(last.end.node, last.end.offset);
  return range;
}

function fuzzyWordRun(
  layerText: string,
  passageText: string,
): { start: number; end: number } | null {
  const wordPattern = /[\p{L}\p{N}]+/gu;
  const layerWords = [...layerText.matchAll(wordPattern)].map((match) => ({
    word: match[0],
    start: match.index ?? 0,
    end: (match.index ?? 0) + match[0].length,
  }));
  const passageWords = [...passageText.matchAll(wordPattern)].map((match) => ({
    word: match[0],
    start: match.index ?? 0,
    end: (match.index ?? 0) + match[0].length,
  }));
  if (passageWords.length < 8 || layerWords.length < 8) return null;

  const layerWindows = new Map<string, number[]>();
  for (let index = 0; index <= layerWords.length - 8; index += 1) {
    const key = layerWords.slice(index, index + 8).map((word) => word.word).join("\u0000");
    const positions = layerWindows.get(key) ?? [];
    positions.push(index);
    layerWindows.set(key, positions);
  }

  let longest: { start: number; end: number; words: number } | null = null;
  for (let index = 0; index <= passageWords.length - 8; index += 1) {
    const key = passageWords.slice(index, index + 8).map((word) => word.word).join("\u0000");
    for (const layerIndex of layerWindows.get(key) ?? []) {
      let before = 0;
      while (
        index > before &&
        layerIndex > before &&
        passageWords[index - before - 1].word === layerWords[layerIndex - before - 1].word
      ) {
        before += 1;
      }
      if (before) continue;
      let count = 8;
      while (
        index + count < passageWords.length &&
        layerIndex + count < layerWords.length &&
        passageWords[index + count].word === layerWords[layerIndex + count].word
      ) {
        count += 1;
      }
      if (!longest || count > longest.words) {
        longest = {
          start: layerWords[layerIndex].start,
          end: layerWords[layerIndex + count - 1].end,
          words: count,
        };
      }
    }
  }
  return longest ? { start: longest.start, end: longest.end } : null;
}

export function findPassageInTextLayer(
  layer: HTMLElement,
  passage: string,
): PassageMatch | null {
  const source = passage.trim();
  if (!source) return null;
  const content = readLayer(layer);
  const normalizedLayer = normalize(content.text, content.points);
  const passagePoints = Array.from(source, (_, index) => ({ node: document.createTextNode(source[index]), offset: 0 }));
  const normalizedPassage = normalize(source, passagePoints).text;
  if (!normalizedPassage) return null;

  const exactIndex = normalizedLayer.text.indexOf(normalizedPassage);
  if (exactIndex >= 0) {
    const range = makeRange(
      normalizedLayer.characters,
      exactIndex,
      exactIndex + normalizedPassage.length,
    );
    return range ? { range, text: range.toString(), fuzzy: false } : null;
  }

  const fuzzy = fuzzyWordRun(normalizedLayer.text, normalizedPassage);
  if (!fuzzy) return null;
  const range = makeRange(normalizedLayer.characters, fuzzy.start, fuzzy.end);
  return range ? { range, text: range.toString(), fuzzy: true } : null;
}
