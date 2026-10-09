import { useEffect, useRef, useState } from "react";

type Props = {
  images: string[];
  alt: string;
  previousLabel: string;
  nextLabel: string;
  imageLabel: string;
};

export default function CategoryCarousel({
  images,
  alt,
  previousLabel,
  nextLabel,
  imageLabel,
}: Props) {
  const [index, setIndex] = useState(0);
  const touchStart = useRef<number | null>(null);
  const gallery = images.filter(Boolean);

  useEffect(() => setIndex(0), [images.join("|")]);

  if (!gallery.length) return null;

  const show = (next: number) => {
    setIndex((next + gallery.length) % gallery.length);
  };
  const finishSwipe = (clientX: number) => {
    if (touchStart.current === null) return;
    const distance = clientX - touchStart.current;
    touchStart.current = null;
    if (Math.abs(distance) < 36) return;
    show(index + (distance < 0 ? 1 : -1));
  };

  return (
    <div
      className="category-carousel"
      onTouchStart={(event) => {
        touchStart.current = event.changedTouches[0]?.clientX ?? null;
      }}
      onTouchEnd={(event) => {
        const clientX = event.changedTouches[0]?.clientX;
        if (typeof clientX === "number") finishSwipe(clientX);
      }}
    >
      <img
        src={gallery[index]}
        alt={`${alt} ${imageLabel} ${index + 1}`}
        loading="lazy"
        draggable={false}
      />
      {gallery.length > 1 && (
        <>
          <button
            type="button"
            className="category-carousel-arrow previous"
            aria-label={previousLabel}
            onClick={(event) => {
              event.stopPropagation();
              show(index - 1);
            }}
          >
            ‹
          </button>
          <button
            type="button"
            className="category-carousel-arrow next"
            aria-label={nextLabel}
            onClick={(event) => {
              event.stopPropagation();
              show(index + 1);
            }}
          >
            ›
          </button>
          <div className="category-carousel-pages" aria-label={`${alt} ${imageLabel}`}>
            {gallery.map((image, page) => (
              <button
                type="button"
                key={image}
                className={page === index ? "active" : ""}
                aria-label={`${imageLabel} ${page + 1}`}
                aria-current={page === index ? "true" : undefined}
                onClick={(event) => {
                  event.stopPropagation();
                  show(page);
                }}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
