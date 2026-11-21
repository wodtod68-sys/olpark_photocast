import type { ReactNode } from 'react';
import styles from './TopBar.module.css';

export function TopBar({ back, backLabel, children }: { back: string; backLabel: string; children?: ReactNode }) {
  return (
    <nav className={styles.bar}>
      <a href={back} className={styles.back}>
        ← {backLabel}
      </a>
      {children}
    </nav>
  );
}
