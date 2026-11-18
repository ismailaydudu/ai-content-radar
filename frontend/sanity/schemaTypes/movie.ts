import {defineField, defineType} from 'sanity'

export default defineType({
  name: 'movie',
  title: 'Film Analizi',
  type: 'document',
  fields: [
    defineField({
      name: 'tmdbId',
      title: 'TMDB ID',
      type: 'number',
      readOnly: true,
      validation: (rule) => rule.integer().positive(),
    }),
    defineField({
      name: 'title',
      title: 'Film Adı',
      type: 'string',
    }),
    defineField({
      name: 'overview',
      title: 'Film Özeti',
      type: 'text',
    }),
    defineField({
      name: 'targetAudience',
      title: 'Hedef Kitle',
      type: 'string',
    }),
    defineField({
      name: 'threeWordSummary',
      title: '3 Kelimelik Özet',
      type: 'string',
    }),
    defineField({
      name: 'radarScore',
      title: 'Radar Skoru',
      type: 'number',
      validation: (rule) => rule.integer().min(1).max(10),
    }),
  ],
})
