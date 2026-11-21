import styles from './ForecastImage.module.css';

// 사진은 테두리·모서리 없이 주어진 영역을 꽉 채운다
export function ForecastImage({ src, alt }: { src: string | null; alt: string }) {
  return (
    <figure className={styles.frame}>
      {src && <img className={styles.img} src={src} alt={alt} />}
      <span className={styles.tag}>AI 예상 이미지</span>
    </figure>
  );
}
