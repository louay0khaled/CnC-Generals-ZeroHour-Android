# Generals UI Pro — All Menus

حزمة واجهات لقوائم Generals: Zero Hour مبنية على بنية BIGF المستخدمة في اللعبة.

## ماذا تحتوي؟
- جميع ملفات `Window/Menus/*.wnd` الموجودة في مشروع Control Bar Pro.
- الملفات المعدلة في `GameFilesEdited` تستبدل النسخ الأصلية عندما تكون متوفرة.
- الناتج: `GeneralsUIPro_AllMenus.big`.

## البناء
يوجد GitHub Action في:
`.github/workflows/build-ui-pro.yml`

الـAction يحمّل مستودع TheSuperHackers/GeneralsControlBar، يجمع ملفات القوائم، ويبني BIGF، ثم يحفظ الناتج داخل:
`UIPro/Release/GeneralsUIPro_AllMenus.big`

## المصدر والترخيص
نستخدم بنية وملفات منشورة في مستودع:
https://github.com/TheSuperHackers/GeneralsControlBar

ترخيص المستودع المذكور MIT حسب ملف LICENSE الخاص به. أصول Generals/Zero Hour الأصلية المملوكة لـEA ليست جزءاً من هذا الترخيص.

## ملاحظة
هذا الإصدار هو حزمة القوائم/النوافذ. مرحلة التصميم الجديدة للهواتف (Touch UI، أحجام الأزرار، الخطوط، الألوان، RTL وغيرها) تُبنى فوق هذه الطبقة لاحقاً.


Build workflow fix applied: BIG files are force-added because the parent project ignores `*.big`.
