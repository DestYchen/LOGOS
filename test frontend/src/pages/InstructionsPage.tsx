import { Link } from "react-router-dom";

import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";

function InstructionsPage() {
  return (
    <div className="mx-auto w-full max-w-4xl space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold">ЛОГОС — инструкция пользователя</h1>
          <p className="text-sm text-muted-foreground">Справочник по основным сценариям работы в ЛОГОС.</p>
        </div>
        <Button asChild variant="secondary">
          <Link to="/feedback">К обратной связи</Link>
        </Button>
      </header>

      <Card className="rounded-3xl border bg-background">
        <CardHeader>
          <CardTitle>Инструкция</CardTitle>
        </CardHeader>
        <CardContent className="space-y-8 text-sm leading-relaxed text-foreground">
          <section id="содержание" className="scroll-mt-24 space-y-3">
            <h2 className="text-xl font-semibold">Содержание</h2>
            <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
              <li>
                <a className="underline-offset-4 hover:underline" href="#быстрый-старт-рекомендуемый-сценарий">
                  Быстрый старт (рекомендуемый сценарий)
                </a>
              </li>
              <li>
                <a className="underline-offset-4 hover:underline" href="#назначение-логос">
                  Назначение Логос
                </a>
              </li>
              <li>
                <a className="underline-offset-4 hover:underline" href="#новый-пакет-загрузка">
                  Новый пакет (загрузка)
                </a>
              </li>
              <li>
                <a className="underline-offset-4 hover:underline" href="#сводка-по-пакету">
                  Сводка по пакету
                </a>
              </li>
              <li>
                <a className="underline-offset-4 hover:underline" href="#матрица-полей-сверка-данных-между-документами">
                  Матрица полей (сверка данных между документами)
                </a>
              </li>
              <li>
                <a className="underline-offset-4 hover:underline" href="#проверка-документов-исправление-ошибок">
                  Проверка документов (исправление ошибок)
                </a>
              </li>
              <li>
                <a className="underline-offset-4 hover:underline" href="#история-ранее-обработанные-пакеты">
                  История (ранее обработанные пакеты)
                </a>
              </li>
              <li>
                <a className="underline-offset-4 hover:underline" href="#обратная-связь">
                  Обратная связь
                </a>
              </li>
              <li>
                <a className="underline-offset-4 hover:underline" href="#типовые-ситуации">
                  Типовые ситуации
                </a>
              </li>
              <li>
                <a className="underline-offset-4 hover:underline" href="#выгрузка-результата-xlsx">
                  Выгрузка результата (XLSX)
                </a>
              </li>
              <li>
                <a className="underline-offset-4 hover:underline" href="#основные-разделы">
                  Основные разделы
                </a>
              </li>
              <li>
                <a className="underline-offset-4 hover:underline" href="#нам-известно-об-этом">
                  Нам известно об этом
                </a>
              </li>
            </ul>
          </section>

          <section id="быстрый-старт-рекомендуемый-сценарий" className="scroll-mt-24 space-y-3">
            <h2 className="text-xl font-semibold">Быстрый старт (рекомендуемый сценарий)</h2>
            <ol className="list-decimal space-y-1 pl-5 text-muted-foreground">
              <li>Откройте раздел Новый пакет.</li>
              <li>При необходимости укажите Название пакета (если оставить пустым, будет использована дата загрузки).</li>
              <li>Загрузите файлы пакета (PDF/Word/ Excel/изображения) и нажмите Продолжить.</li>
              <li>Откройте Сводку по пакету и проверьте Матрицу полей.</li>
              <li>При необходимости нажмите Открыть проверку и выполните исправления.</li>
              <li>Для выгрузки результата нажмите Скачать XLSX.</li>
            </ol>
          </section>

          <section id="назначение-логос" className="scroll-mt-24 space-y-3">
            <h2 className="text-xl font-semibold">Назначение Логос</h2>
            <p className="text-muted-foreground">
              Логос — программное обеспечение для сотрудников отдела логистики, предназначенное для цифровизации и ускорения документооборота по поставкам. Система заменяет ручную сверку пакетов документов: извлекает данные из загруженных файлов и сопоставляет (сверяет) поля документов.
            </p>
          </section>

          <section id="новый-пакет-загрузка" className="scroll-mt-24 space-y-4">
            <div className="space-y-2">
              <h2 className="text-xl font-semibold">Новый пакет (загрузка)</h2>
              <blockquote className="rounded-2xl border border-primary/20 bg-primary/5 px-4 py-3 text-muted-foreground">
                <strong>Назначение:</strong> загрузка документов одной поставки для автоматического анализа и сверки.
              </blockquote>
            </div>

            <div className="space-y-2">
              <h3 className="text-lg font-semibold">Порядок действий</h3>
              <ol className="list-decimal space-y-1 pl-5 text-muted-foreground">
                <li>В поле Название пакета укажите наименование (например: «Поставка февраль 2026»). В случае если поле не заполнено — система присваивает имя по дате загрузки.</li>
                <li>В зоне загрузки выберите файлы или перетащите их мышью.</li>
                <li>Нажмите Продолжить для перехода в окно предпросмотра.</li>
                <li>В окне предпросмотра при необходимости можно повернуть либо удалить документ.</li>
                <li>Нажмите Готово для запуска обработки.</li>
              </ol>
              <blockquote className="rounded-2xl border border-primary/20 bg-primary/5 px-4 py-3 text-muted-foreground">
                <strong>Результат:</strong> Программа начинает обработку пакета документов
              </blockquote>
            </div>
          </section>

          <section id="сводка-по-пакету" className="scroll-mt-24 space-y-4">
            <div className="space-y-2">
              <h2 className="text-xl font-semibold">Сводка по пакету</h2>
              <p className="text-muted-foreground">Раздел предназначен для просмотра результата обработки и управления пакетом.</p>
            </div>

            <div className="space-y-2">
              <h3 className="text-lg font-semibold">Состав пакета</h3>
              <p className="text-muted-foreground">В блоке Состав пакета отображаются требуемые типы документов и их статус:</p>
              <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
                <li>Статус: Есть - документ загружен и распознан;</li>
                <li>Статус: Нет - документ отсутствует в пакете.</li>
              </ul>
              <p className="text-muted-foreground">Также может отображаться уведомление о недостающих документах.</p>
            </div>

            <div className="space-y-2">
              <h3 className="text-lg font-semibold">Доступные действия</h3>
              <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
                <li>Добавить документы - добавление файлов в уже обработанный пакет (например, если документ не был загружен ранее).</li>
                <li>Открыть проверку - переход к экрану контроля/исправления распознанных данных.</li>
                <li>Скачать XLSX - выгрузка матрицы полей в формате Excel.</li>
              </ul>
            </div>
          </section>

          <section id="матрица-полей-сверка-данных-между-документами" className="scroll-mt-24 space-y-4">
            <div className="space-y-2">
              <h2 className="text-xl font-semibold">Матрица полей (сверка данных между документами)</h2>
              <p className="text-muted-foreground">Матрица полей — таблица, где:</p>
              <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
                <li>строки — наименования полей (например: номер документа, дата, покупатель и т.д.);</li>
                <li>столбцы — документы пакета (например: INVOICE, PACKING_LIST, VETERINARY_CERTIFICATE);</li>
                <li>значения — распознанные системой данные из документов.</li>
              </ul>
            </div>

            <div className="space-y-2">
              <h3 className="text-lg font-semibold">Обозначения в матрице</h3>
              <p className="text-muted-foreground">В матрице используются состояния:</p>
              <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
                <li>Опорный документ — документ, относительно которого выполняется сопоставление якорных полей.</li>
                <li>Совпадает — значение поля совпадает с опорным документом.</li>
                <li>Нет значения — значение не найдено/не заполнено.</li>
                <li>Значение отличается — значение отличается от опорного документа.</li>
              </ul>
            </div>

            <div className="space-y-2">
              <h3 className="text-lg font-semibold">Показать различия</h3>
              <p className="text-muted-foreground">
                Кнопка Показать различия подсвечивает места, где значения полей отличаются, для ускорения контроля.
              </p>
            </div>

            <div className="space-y-2">
              <h3 className="text-lg font-semibold">Предпросмотр документа</h3>
              <p className="text-muted-foreground">Кнопка Предпросмотр документа открывает справа область просмотра.</p>
              <p className="text-muted-foreground">После включения предпросмотра:</p>
              <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
                <li>наведите курсор на поле/ячейку в матрице;</li>
                <li>в области предпросмотра будет показан документ, из которого получено значение.</li>
              </ul>
            </div>

            <div className="space-y-2">
              <h3 className="text-lg font-semibold">Навигация по матрице</h3>
              <p className="text-muted-foreground">
                В верхней части матрицы доступны элементы навигации (например, стрелки) для выравнивания больших таблиц по правому/левому столбцу
              </p>
            </div>
          </section>

          <section id="проверка-документов-исправление-ошибок" className="scroll-mt-24 space-y-4">
            <div className="space-y-2">
              <h2 className="text-xl font-semibold">Проверка документов (исправление ошибок)</h2>
              <blockquote className="rounded-2xl border border-primary/20 bg-primary/5 px-4 py-3 text-muted-foreground">
                <strong>Назначение:</strong> уточнение распознанных значений, обязательных полей и полей с низкой уверенностью.
              </blockquote>
            </div>

            <div className="space-y-2">
              <h3 className="text-lg font-semibold">Переход в проверку</h3>
              <ol className="list-decimal space-y-1 pl-5 text-muted-foreground">
                <li>В разделе Сводка по пакету нажмите Открыть проверку.</li>
              </ol>
            </div>

            <div className="space-y-2">
              <h3 className="text-lg font-semibold">Экран проверки</h3>
              <p className="text-muted-foreground">На экране отображаются:</p>
              <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
                <li>выбранный документ (с возможностью переключения Документ 1 из N);</li>
                <li>тип документа (выпадающий список Тип документа);</li>
                <li>список проблемных полей слева и предпросмотр документа справа.</li>
              </ul>
            </div>

            <div className="space-y-2">
              <h3 className="text-lg font-semibold">Обязательные поля</h3>
              <p className="text-muted-foreground">В блоке Обязательные поля требуется заполнить значения вручную.</p>
              <ol className="list-decimal space-y-1 pl-5 text-muted-foreground">
                <li>Введите значение в поле.</li>
                <li>Подтвердите ввод (кнопка подтверждения рядом с полем).</li>
              </ol>
            </div>

            <div className="space-y-2">
              <h3 className="text-lg font-semibold">Поля с низкой уверенностью</h3>
              <p className="text-muted-foreground">В блоке Поля с низкой уверенностью система предлагает распознанные значения, требующие проверки.</p>
              <ol className="list-decimal space-y-1 pl-5 text-muted-foreground">
                <li>Проверьте значение и при необходимости исправьте.</li>
                <li>Подтвердите корректность.</li>
              </ol>
            </div>

            <div className="space-y-2">
              <h3 className="text-lg font-semibold">Подсветка фрагментов документа</h3>
              <p className="text-muted-foreground">
                При просмотре документа система может подсвечивать области, из которых считывались значения (для удобства проверки).
              </p>
            </div>

            <div className="space-y-2">
              <h3 className="text-lg font-semibold">Сохранение и перерасчёт</h3>
              <p className="text-muted-foreground">После внесения изменений нажмите Сохранить и пересчитать.</p>
              <blockquote className="rounded-2xl border border-primary/20 bg-primary/5 px-4 py-3 text-muted-foreground">
                <strong>Результат:</strong> данные обновляются, матрица полей пересчитывается.
              </blockquote>
            </div>

            <div className="space-y-2">
              <h3 className="text-lg font-semibold">Удаление документа</h3>
              <p className="text-muted-foreground">
                Кнопка Удалить документ удаляет выбранный файл из пакета. Используйте действие, если документ загружен ошибочно или не относится к поставке.
              </p>
            </div>
          </section>

          <section id="история-ранее-обработанные-пакеты" className="scroll-mt-24 space-y-4">
            <div className="space-y-2">
              <h2 className="text-xl font-semibold">История (ранее обработанные пакеты)</h2>
              <blockquote className="rounded-2xl border border-primary/20 bg-primary/5 px-4 py-3 text-muted-foreground">
                <strong>Назначение:</strong> быстрый доступ к обработанным пакетам.
              </blockquote>
            </div>

            <div className="space-y-2">
              <h3 className="text-lg font-semibold">Возможности</h3>
              <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
                <li>просмотр списка пакетов (сверху отображаются более свежие);</li>
                <li>открытие выбранного пакета для просмотра результатов;</li>
                <li>контроль статуса обработки (например, «Завершено»).</li>
                <li>удаление определенного пакета (при нажатии на три точки)</li>
              </ul>
            </div>
          </section>

          <section id="обратная-связь" className="scroll-mt-24 space-y-4">
            <div className="space-y-2">
              <h2 className="text-xl font-semibold">Обратная связь</h2>
              <p className="text-muted-foreground">Раздел предназначен для отправки сообщения команде разработки.</p>
            </div>

            <div className="space-y-2">
              <h3 className="text-lg font-semibold">Порядок действий</h3>
              <ol className="list-decimal space-y-1 pl-5 text-muted-foreground">
                <li>Выберите Тип обращения: Проблема или Предложение по улучшению.</li>
                <li>Укажите Тему и заполните Описание (как работает сейчас / как должно работать).</li>
                <li>При необходимости укажите контакт в Telegram (необязательно).</li>
                <li>Добавьте скриншоты (до 5 изображений JPG/PNG, размером до 5 МБ каждое).</li>
                <li>Нажмите Отправить.</li>
              </ol>
            </div>
          </section>

          <section id="типовые-ситуации" className="scroll-mt-24 space-y-4">
            <h2 className="text-xl font-semibold">Типовые ситуации</h2>

            <div className="space-y-2">
              <h3 className="text-lg font-semibold">В матрице есть “Нет значения”.</h3>
              <p className="text-muted-foreground">
                Значение не было распознано или отсутствует в документе. Рекомендуется открыть Проверку и заполнить/уточнить поле вручную (если поле является обязательным или критичным).
              </p>
            </div>

            <div className="space-y-2">
              <h3 className="text-lg font-semibold">В матрице “Значение отличается”.</h3>
              <p className="text-muted-foreground">
                Требуется контроль: возможна ошибка в документе или различия между документами. Используйте Показать различия и/или Предпросмотр документа для проверки источника.
              </p>
            </div>

            <div className="space-y-2">
              <h3 className="text-lg font-semibold">Документ отсутствует в пакете.</h3>
              <ol className="list-decimal space-y-1 pl-5 text-muted-foreground">
                <li>Нажмите Добавить документы в сводке пакета и загрузите недостающий файл.</li>
              </ol>
            </div>
          </section>

          <section id="выгрузка-результата-xlsx" className="scroll-mt-24 space-y-4">
            <div className="space-y-2">
              <h2 className="text-xl font-semibold">Выгрузка результата (XLSX)</h2>
              <p className="text-muted-foreground">Для получения результата в Excel:</p>
              <ol className="list-decimal space-y-1 pl-5 text-muted-foreground">
                <li>Откройте Сводка по пакету.</li>
                <li>Нажмите Скачать XLSX.</li>
              </ol>
              <blockquote className="rounded-2xl border border-primary/20 bg-primary/5 px-4 py-3 text-muted-foreground">
                <strong>Результат:</strong> будет выгружена актуальная матрица полей по текущему состоянию пакета.
              </blockquote>
            </div>
          </section>

          <section id="основные-разделы" className="scroll-mt-24 space-y-4">
            <div className="space-y-2">
              <h2 className="text-xl font-semibold">Основные разделы</h2>
              <p className="text-muted-foreground">В левом меню доступны:</p>
              <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
                <li>Новый пакет — создание и загрузка пакета документов на обработку.</li>
                <li>История — просмотр ранее обработанных пакетов.</li>
                <li>Обратная связь — отправка сообщения команде разработки (проблема/предложение).</li>
              </ul>
            </div>
          </section>

          <section id="нам-известно-об-этом" className="scroll-mt-24 space-y-4">
            <div className="space-y-2">
              <h2 className="text-xl font-semibold">Нам известно об этом</h2>
              <p className="text-muted-foreground">
                Список вещей, о которых команде разработчиков уже известно на данный момент. Сообщать о них не нужно.
              </p>
            </div>

            <div className="space-y-2">
              <h3 className="text-lg font-semibold">Нам известно</h3>
              <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
                <li>некорректное отображение превью в Матрице полей</li>
                <li>некорректная работа подсветки проверенного поля документа в меню Проверка документа (исправление ошибок)</li>
              </ul>
            </div>
          </section>
        </CardContent>
      </Card>
    </div>
  );
}

export default InstructionsPage;
