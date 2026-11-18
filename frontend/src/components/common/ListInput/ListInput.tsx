import React, { useState } from 'react';
import { useIntl } from 'react-intl';
import {
  Button,
  IconButton,
  Pagination,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  TextInput,
} from '@carbon/react';
import { Add, SubtractAlt } from '@carbon/icons-react';
import styles from './ListInput.module.scss';
import { messages } from './ListInput.messages';

const PAGE_SIZE = 5;

/**
 * Props for {@link ListInput}.
 */
interface ListInputProps {
  /** HTML `id` forwarded to the underlying `TextInput`. */
  id: string;
  /** Controlled list of committed items. */
  items: string[];
  /** Called with the updated array whenever an item is added or removed. */
  onChange: (items: string[]) => void;
  /** Accessible label for the text input (visually hidden). */
  labelText: string;
  /** Header text of the table listing the committed items. */
  tableTitle: string;
  /** Placeholder shown inside the text input when empty. */
  placeholder?: string;
  /** Helper text rendered below the input. */
  helperText?: string;
}

/**
 * Text input with an explicit **Add +** button and a table of committed items.
 *
 * Behaviour:
 * - Pending text is committed only on Enter, comma, or clicking **Add +**.
 * - Losing focus never commits or clears the pending text, so users can switch
 *   to another application (e.g. to copy a filename) and return to append.
 * - Adding a value that already exists is rejected: the text is kept and the
 *   input is flagged invalid with an explanatory message until it is edited.
 * - Each row has a remove button; the table is paginated, and adding an item
 *   jumps to the page that contains it.
 */
export function ListInput({
  id,
  items,
  onChange,
  labelText,
  tableTitle,
  placeholder,
  helperText,
}: ListInputProps): React.JSX.Element {
  const intl = useIntl();
  const [inputValue, setInputValue] = useState('');
  const [duplicateValue, setDuplicateValue] = useState<string | null>(null);
  const [page, setPage] = useState(1);

  const pageCount = Math.max(1, Math.ceil(items.length / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount);
  const pageItems = items.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);

  const commit = (): void => {
    const trimmed = inputValue.trim().replace(/,+$/, '').trim();
    if (trimmed && items.includes(trimmed)) {
      setDuplicateValue(trimmed);
      return;
    }
    if (trimmed) {
      onChange([...items, trimmed]);
      // Show the page that contains the newly added item
      setPage(Math.ceil((items.length + 1) / PAGE_SIZE));
    }
    setInputValue('');
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>): void => {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      commit();
    }
  };

  const handleRemove = (item: string): void => {
    onChange(items.filter((i) => i !== item));
  };

  return (
    <div className={styles.wrapper}>
      <div className={styles.inputRow}>
        <div className={styles.inputCell}>
          <TextInput
            id={id}
            labelText={labelText}
            hideLabel
            placeholder={placeholder}
            value={inputValue}
            onChange={(e) => {
              setInputValue(e.target.value);
              setDuplicateValue(null);
            }}
            onKeyDown={handleKeyDown}
            helperText={helperText}
            invalid={duplicateValue !== null}
            invalidText={
              duplicateValue !== null
                ? intl.formatMessage(messages.duplicateValue, { value: duplicateValue })
                : undefined
            }
          />
        </div>

        <Button
          kind="tertiary"
          size="md"
          renderIcon={Add}
          className={styles.addButton}
          disabled={!inputValue.trim()}
          onClick={commit}
        >
          {intl.formatMessage(messages.addButton)}
        </Button>
      </div>

      {items.length > 0 && (
        <div className={styles.tableWrapper}>
          <Table size="lg" aria-label={tableTitle}>
            <TableHead>
              <TableRow>
                <TableHeader colSpan={2}>{tableTitle}</TableHeader>
              </TableRow>
            </TableHead>
            <TableBody>
              {pageItems.map((item) => (
                <TableRow key={item}>
                  <TableCell className={styles.valueCell}>{item}</TableCell>
                  <TableCell className={styles.removeCell}>
                    <IconButton
                      kind="ghost"
                      size="sm"
                      label={intl.formatMessage(messages.removeItem)}
                      onClick={() => { handleRemove(item); }}
                    >
                      <SubtractAlt />
                    </IconButton>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>

          {pageCount > 1 && (
            <Pagination
              page={currentPage}
              pageSize={PAGE_SIZE}
              pageSizes={[PAGE_SIZE]}
              totalItems={items.length}
              itemsPerPageText={intl.formatMessage(messages.itemsPerPage)}
              backwardText={intl.formatMessage(messages.previousPage)}
              forwardText={intl.formatMessage(messages.nextPage)}
              itemRangeText={(min: number, max: number, total: number) =>
                intl.formatMessage(messages.itemRange, { min, max, total })}
              pageRangeText={(current: number, total: number) =>
                intl.formatMessage(messages.pageRange, { current, total })}
              onChange={({ page: p }) => { setPage(p); }}
            />
          )}
        </div>
      )}
    </div>
  );
}
