import styles from './ForecastImage.module.css';

interface Props {
  src: string | null;
  alt: string;
  position?: string; // 사진을 잘라 보여줄 때의 중심점 (spot.photo.position)
  summary?: string; // 사진 아래 한 줄 조건 요약
}

// 사진은 테두리·모서리 없이 주어진 영역을 꽉 채운다. src가 아직 없으면 만드는 중 표시
export function ForecastImage({ src, alt, position, summary }: Props) {
  return (
    <figure className={styles.frame}>
      {src ? (
        <img className={styles.img} src={src} alt={alt} style={position ? { objectPosition: position } : undefined} />
      ) : (
        <p className={styles.loading} role="status">
          예상 이미지 만드는 중…
        </p>
      )}
      <span className={styles.tag}>AI 예상 이미지</span>
      {src && summary && <figcaption className={styles.summary}>{summary}</figcaption>}
    </figure>
  );
}
