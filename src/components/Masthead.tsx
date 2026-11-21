import styles from './Masthead.module.css';

export function Masthead() {
  return (
    <header className={styles.masthead}>
      <a className={styles.title} href="#/">
        올팍 포토캐스트
      </a>
    </header>
  );
}
