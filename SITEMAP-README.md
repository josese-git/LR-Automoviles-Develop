# Cómo Usar el Generador de Sitemap

## Requisitos Previos

Para ejecutar el script `generate-sitemap.js`, necesitas tener **Node.js** instalado en tu sistema.

### Instalar Node.js

1. Descarga Node.js desde: https://nodejs.org/
2. Instala la versión LTS (recomendada)
3. Verifica la instalación abriendo PowerShell y ejecutando:
   ```bash
   node --version
   npm --version
   ```

## Uso del Script

Una vez que tengas Node.js instalado:

### 1. Instalar Dependencias

Abre PowerShell en la carpeta del proyecto y ejecuta:

```bash
cd "c:\Users\Josese\Documents\JVeloce Develop"
npm install
```

Esto instalará Firebase y las dependencias necesarias.

### 2. Generar el Sitemap

Ejecuta el script:

```bash
npm run generate-sitemap
```

O directamente:

```bash
node generate-sitemap.js
```

### 3. Resultado

El script:
- ✅ Se conectará a Firebase Firestore
- ✅ Obtendrá todos los vehículos y sus imágenes
- ✅ Generará un nuevo `sitemap.xml` con:
  - Todas las URLs de vehículos
  - Todas las imágenes (principal + galería exterior + galería interior)
  - Metadatos de cada imagen (caption con marca, modelo, año y vista)
- ✅ Mostrará estadísticas: total de URLs y total de imágenes indexadas

### 4. Subir a Google Search Console

Después de generar el sitemap:

1. Sube el archivo `sitemap.xml` actualizado a tu servidor
2. Ve a Google Search Console: https://search.google.com/search-console
3. Selecciona tu propiedad (autosjveloce.com)
4. Ve a "Sitemaps" en el menú lateral
5. Envía el sitemap: `https://autosjveloce.com/sitemap.xml`

## Cuándo Ejecutar el Script

Deberías ejecutar este script:
- ✅ Cada vez que añadas un nuevo vehículo
- ✅ Cada vez que actualices las imágenes de un vehículo
- ✅ Una vez al mes como mantenimiento

## Alternativa Sin Node.js

Si no quieres instalar Node.js, puedes actualizar el sitemap manualmente:

1. Abre `sitemap.xml`
2. Para cada vehículo nuevo, añade:

```xml
<url>
    <loc>https://autosjveloce.com/Coches/detalle.html?id=ID-DEL-COCHE</loc>
    <lastmod>2026-02-02</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.8</priority>
    <image:image>
        <image:loc>URL-DE-LA-IMAGEN</image:loc>
        <image:caption>Marca Modelo Año - Vista frontal</image:caption>
    </image:image>
    <!-- Repite para cada imagen del coche -->
</url>
```

**Nota**: El script automatizado es mucho más eficiente y reduce errores.
