import type { InjectionKey, Ref } from 'vue'

export const updateRequiredKey: InjectionKey<Readonly<Ref<boolean>>> = Symbol('update-required')
